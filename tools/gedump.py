#!/usr/bin/env python3
"""List the draws in a PPSSPP GE frame dump (.ppdmp, format v5/v6, zstd).

For each PRIM: draw index, prim type, vertex count, vtype, through-mode flag,
texture enable + address, framebuffer address/width, and the vertex bounding box.

usage: gedump.py FILE.ppdmp [--through]
"""
import struct
import sys

import zstandard

CT_REGISTERS, CT_VERTICES, CT_INDICES = 1, 2, 3
COMP = [0, 1, 2, 4]


def read_dump(path):
    d = open(path, 'rb').read()
    magic, version = d[:8], struct.unpack_from('<I', d, 8)[0]
    assert magic == b'PPSSPPGE', 'not a GE dump'
    off = 24
    ncmd, bufsz = struct.unpack_from('<II', d, off)
    off += 8
    blobs = []
    for _ in range(2):
        sz = struct.unpack_from('<I', d, off)[0]
        off += 4
        blobs.append(zstandard.ZstdDecompressor().decompress(d[off:off + sz], max_output_size=64 << 20))
        off += sz
    cmds = [struct.unpack_from('<BII', blobs[0], i * 9) for i in range(ncmd)]
    return version, cmds, blobs[1]


def vertex_layout(vtype):
    tc, col, nrm, pos = vtype & 3, (vtype >> 2) & 7, (vtype >> 5) & 3, (vtype >> 7) & 3
    wt, wcount = (vtype >> 9) & 3, ((vtype >> 14) & 7) + 1
    off, big = 0, 1

    def add(size, n):
        nonlocal off, big
        off = (off + size - 1) & ~(size - 1)
        start = off
        off += size * n
        big = max(big, size)
        return start
    if wt:
        add(COMP[wt], wcount)
    if tc:
        add(COMP[tc], 2)
    if col:
        add(4 if col == 7 else 2, 1)
    if nrm:
        add(COMP[nrm], 3)
    posoff = add(COMP[pos], 3) if pos else 0
    vsize = (off + big - 1) & ~(big - 1)
    return posoff, vsize, pos


def positions(blob, vtype, n):
    posoff, vsize, pos = vertex_layout(vtype)
    out = []
    for i in range(n):
        o = i * vsize + posoff
        if o + 12 > len(blob):
            break
        if pos == 2:
            out.append(struct.unpack_from('<hh', blob, o))
        elif pos == 3:
            out.append(struct.unpack_from('<ff', blob, o))
        elif pos == 1:
            out.append(struct.unpack_from('<bb', blob, o))
    return out


def draws(path):
    version, cmds, buf = read_dump(path)
    st = {'vtype': 0, 'tbp0': 0, 'tbw0': 0, 'fbp': 0, 'fbw': 0, 'tme': 0, 'region': None}
    verts = b''
    n = 0
    for typ, sz, ptr in cmds:
        if typ == CT_VERTICES:
            verts = buf[ptr:ptr + sz]
        elif typ == CT_REGISTERS:
            for i in range(sz // 4):
                w = struct.unpack_from('<I', buf, ptr + 4 * i)[0]
                c, a = w >> 24, w & 0xFFFFFF
                if c == 0x00 and (a >> 20) in (0xA, 0xB, 0xD):
                    yield dict(nop=a)
                    continue
                if c == 0x12:
                    st['vtype'] = a
                elif c == 0xA0:
                    st['tbp0'] = a
                elif c == 0xA8:
                    st['tbw0'] = a
                elif c == 0x9C:
                    st['fbp'] = a
                elif c == 0x9D:
                    st['fbw'] = a
                elif c == 0x1E:
                    st['tme'] = a & 1
                elif c == 0x04:
                    count = a & 0xFFFF
                    vt = st['vtype']
                    pts = positions(verts, vt, count)
                    tex = ((st['tbw0'] >> 16) & 0xF) << 24 | st['tbp0']
                    bbox = None
                    if pts:
                        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                        bbox = (min(xs), min(ys), max(xs), max(ys))
                    yield dict(i=n, prim=(a >> 16) & 7, count=count, vtype=vt, through=bool(vt & 0x800000),
                               tme=st['tme'], tex=tex, fb=((st['fbw'] >> 16) & 0xFF) << 24 | st['fbp'],
                               fbw=st['fbw'] & 0xFFFF, bbox=bbox)
                    n += 1


if __name__ == '__main__':
    only_through = '--through' in sys.argv
    for dr in draws(sys.argv[1]):
        if 'nop' in dr:
            a = dr['nop']
            if a >> 20 == 0xA:
                print('  DBG history (newest right): ' + format(a & 0xFFFFF, '020b'))
            elif a >> 20 == 0xB:
                print('  DBG mode=%s switch=%d bottom_ok=%d top=%d tiles_ok=%d hud_ok=%d' % (
                    ('full', 'dialogue', 'hud', 'hud-centre')[a & 3], (a >> 2) & 63, (a >> 8) & 1, (a >> 9) & 255,
                    (a >> 17) & 1, (a >> 18) & 1))
            elif a >> 20 == 0xD:
                print('  DBG switches=%d history at last switch: %s' % ((a >> 12) & 255, format(a & 0xFFF, '012b')))
            else:
                print('  DBG %06X' % a)
            continue
        if only_through and not dr['through']:
            continue
        bb = dr['bbox']
        bbs = '(%7.1f,%7.1f)-(%7.1f,%7.1f)' % bb if bb else '-'
        print('%4d prim=%d n=%-4d vt=%06X %s tme=%d tex=%08X fb=%08X/%-4d %s' % (
            dr['i'], dr['prim'], dr['count'], dr['vtype'], 'T' if dr['through'] else '3', dr['tme'],
            dr['tex'], dr['fb'], dr['fbw'], bbs))
