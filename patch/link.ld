OUTPUT_ARCH(mips)
ENTRY(ccc43_draw_tramp)
/* Code and initialised data go after the module's BSS (see build.py).
 * Zero-initialised variables live in 184 bytes of debug assert strings
 * ("ie2d_prim_filter_psp.cpp" / "ie2d_texbnk_psp.cpp" paths) at 0x089BE420,
 * which build.py clears; they are only ever printed if an engine assert fails.
 * Overflow code (.text2) goes over 1520 bytes of CRI File System error messages at
 * 0x08A21B18 ("E2009091401:Invalid ID." ...), only used when the file system fails;
 * no relocation entries point into that range. */
MEMORY
{
  code (rwx) : ORIGIN = 0x08B6F510, LENGTH = 0xAF0
  vars (rw)  : ORIGIN = 0x089BE420, LENGTH = 184
  cri (rx)   : ORIGIN = 0x08A21B18, LENGTH = 1520
}
SECTIONS
{
  .text2 : { *(.text2) } > cri
  .text : { *(.text.tramp) *(.text) *(.text.*) } > code
  .rodata : { *(.rodata*) } > code
  .data : { *(.data*) *(.sdata*) } > code
  .bss (NOLOAD) : { *(.bss*) *(.sbss*) *(COMMON) } > vars
  /DISCARD/ : { *(.MIPS.abiflags) *(.reginfo) *(.pdr) *(.comment) *(.gnu.attributes) *(.note*) *(.mdebug*) }
}
