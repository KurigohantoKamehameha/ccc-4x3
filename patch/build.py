#!/usr/bin/env python3
"""Build the 4:3 hook code and apply it to a decrypted FATE_MAIN EBOOT.

usage: build.py IN_EBOOT OUT_EBOOT [--hor-minus] [--debug]
  --debug  write the classifier state into the display list (see tools/gedump.py)

How the code is injected:
  The PRX has two LOAD segments: text/data (vaddr 0) and BSS (vaddr 0x229600, NOBITS).
  The BSS segment is turned into a file-backed segment (zeros) extended past its end,
  and the hook code is placed right after the BSS (0x08B6F510). The module image still
  ends before the next 0x1000 boundary (0x08B70000), so the game's heap (allocated
  low-aligned right after the module) stays where it was — required by the English
  translation, which uses fixed heap addresses.
"""
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = 0x08804000
SEG1_VADDR = 0x229600
SEG1_MEMSZ = 0x141F04
CODE_ADDR = 0x08B6F510
LIMIT = 0x08B70000
TEXT2_ADDR = 0x08A21B18
TEXT2_SIZE = 1520

CFLAGS = ('-EL -march=mips2 -Wa,-march=allegrex -mabi=eabi -mgp32 -mfp32 -msingle-float '
          '-mhard-float -fno-pic -mno-abicalls -G0 -Os -ffreestanding -fno-builtin -nostdlib '
          '-mno-check-zero-division -fsingle-precision-constant -mno-gpopt -w').split()


def run(cmd):
    subprocess.run(cmd, check=True)


def build(out_dir, hor_minus, debug=False):
    os.makedirs(out_dir, exist_ok=True)
    defs = (['-DCCC43_HOR_MINUS'] if hor_minus else []) + (['-DCCC43_DEBUG'] if debug else [])
    o1, o2 = os.path.join(out_dir, 'tramp.o'), os.path.join(out_dir, 'ccc43.o')
    elf, binf = os.path.join(out_dir, 'ccc43.elf'), os.path.join(out_dir, 'ccc43.bin')
    run(['mips-linux-gnu-gcc', *CFLAGS, '-c', os.path.join(HERE, 'tramp.S'), '-o', o1])
    run(['mips-linux-gnu-gcc', *CFLAGS, *defs, '-c', os.path.join(HERE, 'ccc43.c'), '-o', o2])
    run(['mips-linux-gnu-ld', '-EL', '-T', os.path.join(HERE, 'link.ld'), o1, o2, '-o', elf])
    run(['mips-linux-gnu-objcopy', '-O', 'binary', '-j', '.text', '-j', '.rodata', '-j', '.data', elf, binf])
    syms = {}
    for line in subprocess.run(['mips-linux-gnu-nm', elf], capture_output=True, text=True, check=True).stdout.splitlines():
        a, _, n = line.split()
        syms[n] = int(a, 16)
    end = 0
    for line in subprocess.run(['mips-linux-gnu-size', '-A', '-x', elf], capture_output=True, text=True, check=True).stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == '.text2':
            syms['__text2_size'] = int(parts[1], 16)
        if len(parts) == 3 and parts[0] == '.cri_vars':
            syms['__cri_vars'], syms['__cri_vars_size'] = int(parts[2], 16), int(parts[1], 16)
        if len(parts) == 3 and parts[0] in ('.text', '.rodata', '.data'):
            end = max(end, int(parts[2], 16) + int(parts[1], 16))
        if len(parts) == 3 and parts[0] == '.bss':
            syms['__bss_start'], syms['__bss_size'] = int(parts[2], 16), int(parts[1], 16)
    bin2 = os.path.join(out_dir, 'ccc43_text2.bin')
    run(['mips-linux-gnu-objcopy', '-O', 'binary', '-j', '.text2', elf, bin2])
    return open(binf, 'rb').read(), syms, end, open(bin2, 'rb').read()


def j(target):
    return 0x08000000 | ((target >> 2) & 0x03FFFFFF)


def jal_rel(target):
    """jal in a relocated slot: the loader adds the module base, so store base-relative."""
    return 0x0C000000 | (((target - BASE) >> 2) & 0x03FFFFFF)


def patch(in_path, out_path, hor_minus=False, debug=False):
    code, syms, end, code2 = build(os.path.join(HERE, '..', 'build', ('hor' if hor_minus else 'vert') + ('-dbg' if debug else '')), hor_minus, debug)
    if end > LIMIT:
        sys.exit('hook code too large: ends at 0x%08X (limit 0x%08X)' % (end, LIMIT))
    d = bytearray(open(in_path, 'rb').read())
    assert d[:4] == b'\x7fELF' and struct.unpack_from('<H', d, 0x10)[0] == 0xFFA0, 'not a decrypted PRX'

    def off(addr):
        return 0xA0 + addr - BASE

    def w(addr, value, expect=None):
        o = off(addr)
        if expect is not None:
            cur = struct.unpack_from('<I', d, o)[0]
            assert cur == expect, 'unexpected word at %08X: %08X (expected %08X)' % (addr, cur, expect)
        struct.pack_into('<I', d, o, value)

    # --- hooks ---
    w(0x08996ABC, j(syms['ccc43_draw_tramp']), 0x308C0007)       # andi t4,a0,7
    w(0x08996AC0, 0x00000000, 0x7CEA1E00)                         # ext t2,a3,24,4
    w(0x08996AA8, jal_rel(syms['ccc43_set_matrix']), 0x0C064E3A)  # jal guSetMatrixInternal
    w(0x08997570, jal_rel(syms['ccc43_scissor']), 0x0C0650F9)     # jal guScissorInternal
    w(0x08996B8C, j(syms['ccc43_drawn_tramp']), 0x27BDFFF0)       # addiu sp,sp,-16 (DrawArrayN)
    for site in (0x089961E4, 0x089962AC, 0x089967E8):             # jal sceDisplaySetFrameBuf
        w(site, jal_rel(syms['ccc43_frame_end']), jal_rel(0x089A68F4))

    # --- zero-initialised hook variables live in unused assert strings (see link.ld) ---
    bss, bss_size = syms.get('__bss_start', 0), syms.get('__bss_size', 0)
    if bss_size:
        assert d[off(0x089BE420):off(0x089BE420) + 2] == b'p:', 'assert strings not where expected'
        d[off(bss):off(bss) + bss_size] = bytes(bss_size)

    # --- overflow code over unused CRI error strings (see link.ld) ---
    if code2:
        assert d[off(TEXT2_ADDR):off(TEXT2_ADDR) + 11] == b'E2009091401', 'CRI strings not where expected'
        assert len(code2) <= TEXT2_SIZE
        d[off(TEXT2_ADDR):off(TEXT2_ADDR) + len(code2)] = code2
    if syms.get('__cri_vars_size'):
        a, n = syms['__cri_vars'], syms['__cri_vars_size']
        assert TEXT2_ADDR <= a and a + n <= TEXT2_ADDR + TEXT2_SIZE
        d[off(a):off(a) + n] = bytes(n)

    # --- segment 1: BSS -> file-backed, extended with the hook code ---
    phoff = struct.unpack_from('<I', d, 0x1C)[0]
    ph1 = phoff + 32
    p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = struct.unpack_from('<8I', d, ph1)
    assert p_vaddr == SEG1_VADDR and p_memsz == SEG1_MEMSZ and p_filesz == 0, 'segment 1 layout differs'
    new_off = (len(d) + 0x3F) & ~0x3F
    code_rel = CODE_ADDR - BASE - SEG1_VADDR
    blob = bytes(code_rel) + code
    filesz = len(blob)
    memsz = end - BASE - SEG1_VADDR
    d += bytes(new_off - len(d)) + blob
    struct.pack_into('<8I', d, ph1, p_type, new_off, p_vaddr, p_paddr, filesz, memsz, 7, p_align)
    open(out_path, 'wb').write(d)
    print('%s: hooks at 0x%08X-0x%08X (%d bytes) + %d bytes at 0x%08X, mode %s' % (
        out_path, CODE_ADDR, end, len(code), len(code2), TEXT2_ADDR, 'Hor-' if hor_minus else 'Vert+'))
    for n in ('ccc43_draw_tramp', 'ccc43_draw', 'ccc43_scissor', 'ccc43_set_matrix', '__bss_start', '__bss_size'):
        print('  %-18s 0x%08X' % (n, syms[n]))


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    patch(args[0], args[1], '--hor-minus' in sys.argv, '--debug' in sys.argv)
