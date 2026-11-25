/* sceGuDrawArray entry hook (0x08996ABC). Entry words replaced with: j ccc43_draw_tramp ; nop */
    .set noreorder
    .set noat
    .text
    .globl ccc43_draw_tramp
ccc43_draw_tramp:
    addiu $sp, $sp, -32
    sw    $ra, 0($sp)
    sw    $a0, 4($sp)
    sw    $a1, 8($sp)
    sw    $a2, 12($sp)
    sw    $a3, 16($sp)
    jal   ccc43_draw          /* EABI: prim, vtype, count, indices, verts($t0) */
    sw    $t0, 20($sp)
    lw    $ra, 0($sp)
    lw    $a0, 4($sp)
    lw    $a1, 8($sp)
    lw    $a2, 12($sp)
    lw    $a3, 16($sp)
    move  $t0, $v0
    addiu $sp, $sp, 32
    /* displaced original instructions */
    andi  $t4, $a0, 0x7
    .word 0x7CEA1E00          /* ext $t2, $a3, 24, 4 */
    j     0x08996AC4
    nop

/* sceGuDrawArrayN entry hook (0x08996B8C): prim a0, vtype a1, count a2, n a3, indices t0, verts t1.
 * Entry word replaced with "j ccc43_drawn_tramp"; the delay slot (relocated lui $v1) runs first. */
    .globl ccc43_drawn_tramp
ccc43_drawn_tramp:
    addiu $sp, $sp, -48
    sw    $ra, 0($sp)
    sw    $a0, 4($sp)
    sw    $a1, 8($sp)
    sw    $a2, 12($sp)
    sw    $a3, 16($sp)
    sw    $t0, 20($sp)
    sw    $t1, 24($sp)
    sw    $v1, 28($sp)
    mult  $a2, $a3
    mflo  $a2                 /* total vertices = count * n */
    move  $a3, $t0            /* indices */
    jal   ccc43_draw
    move  $t0, $t1            /* vertices (5th arg) */
    lw    $ra, 0($sp)
    lw    $a0, 4($sp)
    lw    $a1, 8($sp)
    lw    $a2, 12($sp)
    lw    $a3, 16($sp)
    lw    $t0, 20($sp)
    lw    $v1, 28($sp)
    move  $t1, $v0
    addiu $sp, $sp, 48
    /* displaced original instruction */
    addiu $sp, $sp, -16
    j     0x08996B94
    nop

