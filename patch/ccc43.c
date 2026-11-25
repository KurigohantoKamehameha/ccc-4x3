/*
 * Fate/Extra CCC 4:3 display patch — hooks into the statically linked libgu.
 *
 * The PSP framebuffer is 480x272. On a 4:3 display it is squeezed horizontally by
 * S = (4/3) / (480/272) = 34/45. To keep correct proportions:
 *   - 2D (through-mode) draws and scissor rectangles are shrunk vertically by S
 *     around the screen centre (y = 136): UI keeps full width, ~75% height.
 *   - Perspective projections get their Y scale multiplied by S (Vert+) or their
 *     X scale divided by S (Hor-), chosen at build time with -DCCC43_HOR_MINUS.
 *   - Orthographic projections are treated like 2D (Y shrink).
 * Full-screen draws/scissors (0,0)-(480,272) are left untouched (backgrounds, fades).
 *
 * Built for EABI (same calling convention as the game): 5th integer arg in $t0.
 */

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef short s16;

#define SCREEN_W 480
#define SCREEN_H 272
#define CY 136
#define S_NUM 34
#define S_DEN 45
#define S_F 0.75555556f

/* Game / libgu functions (absolute addresses, module base 0x08804000) */
typedef void *(*GuGetMemoryFn)(int size);
typedef void (*GuSetMatrixInternalFn)(void *ctx, int type, const float *m);
typedef void (*GuScissorInternalFn)(void *ctx, int x, int y, int w, int h);

#define sceGuGetMemory        ((GuGetMemoryFn)0x0899669C)
#define guSetMatrixInternal   ((GuSetMatrixInternalFn)0x089978E8)
#define guScissorInternal     ((GuScissorInternalFn)0x089983E4)


#define TEXT2 __attribute__((section(".text2"), noinline))   /* second code area, see link.ld */

/* Display modes */
#define MODE_FULL 0   /* leave the 2D layer exactly as the game draws it (menus, narration) */
#define MODE_DLG  1   /* dialogue scene: shrink the 2D layer towards the bottom edge */
#define MODE_HUD  2   /* 3D gameplay, HUD elements clear of the middle: shrink each towards its nearest edge */
#define MODE_HUDC 3   /* 3D gameplay with UI across the middle (battle): shrink all of it around the centre */

volatile u32 ccc43_cur_fbp;       /* current draw buffer, read from the display list */
volatile u32 ccc43_switch;        /* frames the classifier has disagreed with the mode */
volatile u32 ccc43_mode;          /* MODE_* (zero-initialised: MODE_FULL) */
static u32 cov_rows[17];          /* 30x17 grid of 16px cells covered by 2D draws this frame */
static u32 box_tiles;             /* 32x32 UI tiles in the lower part of the screen this frame */
static u32 tall_draws;            /* full-height strips (narration panel) this frame */
static u32 persp_frame;           /* a perspective projection was set on the display this frame */
static u32 straddle;              /* 2D draws crossing the screen's middle line this frame */

static void cover(int x0, int y0, int x1, int y1)
{
    int r, c0, c1;
    u32 mask;
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > SCREEN_W) x1 = SCREEN_W;
    if (y1 > SCREEN_H) y1 = SCREEN_H;
    if (x1 <= x0 || y1 <= y0)
        return;
    c0 = x0 >> 4;
    c1 = (x1 - 1) >> 4;
    mask = ((c1 >= 31 ? 0xFFFFFFFFu : ((1u << (c1 + 1)) - 1))) & ~((1u << c0) - 1);
    for (r = y0 >> 4; r <= (y1 - 1) >> 4 && r < 17; r++)
        cov_rows[r] |= mask;
}

TEXT2 static u32 popcount(u32 v)
{
    u32 n = 0;
    while (v) { v &= v - 1; n++; }
    return n;
}

#ifdef CCC43_DEBUG
static u32 dbg_hist, dbg_state, dbg_done, dbg_snap;

/* Debug builds (build.py --debug): GE NOP commands carry the classifier state into PPSSPP frame dumps.
 * NOP payload 0xA_____ = last 20 frames' dialogue test (bit 0 newest);
 * 0xB_____ = mode | switch<<2 | bottom_ok<<8 | top cells<<9 (8 bits) | tiles_ok<<17 | hud_ok<<18;
 * 0xD_____ = mode switches so far (bits 12-19) | dialogue-test history when the last switch happened. */
TEXT2 static void dbg_emit(void)
{
    u32 *list = *(u32 **)0x08AF2CCC;
    u32 *cur = (u32 *)list[2];
    *cur++ = 0x00A00000 | (dbg_hist & 0xFFFFF);
    *cur++ = 0x00B00000 | dbg_state | ccc43_mode | ccc43_switch << 2;
    *cur++ = 0x00D00000 | dbg_snap;
    list[2] = (u32)cur;
    dbg_done = 1;
}
#define DBG(x) x
#else
#define DBG(x)
#endif

/* Classify the frame that was just finished.
 * Dialogue: a wide box across the bottom (rows 12-15 covered across >= 29 of 30 cells) built
 *   from 40-149 32x32 tiles (~90). Menus drawn over it add many more tiles (dump 7: 213). The top
 *   of the screen must stay mostly free (3D view, a portrait) unless a narration panel is fading
 *   in or out over the box (full-height strips), so speaker/narration changes stay in dialogue.
 * HUD: a 3D frame (dungeon, battle) whose 2D layer covers less than 70% of the screen and has
 *   no narration panel. If nothing spans the middle line (dungeon) each draw is shrunk towards
 *   the edge its centre is nearest to; otherwise (battle: panels and banners across the middle,
 *   touching each other) the whole layer is shrunk around the centre so it stays in one piece.
 *   Title, menus, narration and the battle result grid cover more and stay untouched. */
TEXT2 static u32 classify(void)
{
    u32 r, top = 0, total = 0, bottom_ok = 1, tiles = box_tiles, dlg, hud, sep;
    for (r = 12; r <= 15; r++)
        if (popcount(cov_rows[r]) < 29)
            bottom_ok = 0;
    for (r = 0; r < 17; r++) {
        u32 n = popcount(cov_rows[r]);
        if (r <= 9)
            top += n;
        total += n;
    }
    dlg = bottom_ok && tiles >= 40 && tiles < 150 && (top < 210 || tall_draws >= 8);
    hud = persp_frame && total < 510 * 7 / 10 && tall_draws < 8;
    sep = straddle <= 2 && !(cov_rows[8] & cov_rows[9]);
    DBG(dbg_state = bottom_ok << 8 | (top < 255 ? top : 255) << 9 | (tiles >= 40 && tiles < 150) << 17 | hud << 18);
    DBG(dbg_hist = dbg_hist << 1 | dlg);
    for (r = 0; r < 17; r++) {
        cov_rows[r] = 0;
    }
    box_tiles = tall_draws = straddle = persp_frame = 0;
    if (dlg)
        return MODE_DLG;
    if (ccc43_mode == MODE_DLG && top >= 210)
        return MODE_FULL | 0x100;   /* narration / menu right after dialogue: switch at once */
    return (hud && sep) ? MODE_HUD : MODE_FULL;   /* battle: left as drawn (user's choice) */
}

/* The two display buffers live at VRAM 0x00000 and 0x44000 (480x272, 512 stride, 16bpp);
 * everything from 0x88000 up is an off-screen render target. */
static int on_display(void)
{
    return (ccc43_cur_fbp & 0x1FFFFF) < 0x88000;
}

/* The game switches render targets through several code paths (libgu, its own GE
 * command builders), so instead of hooking them all, read the FBP commands it has
 * written into the current display list since the last look. Memory blocks embedded
 * in the list (sceGuGetMemory: BASE + JUMP over the data) are skipped. */
static u32 *scan_p;

static void scan_list(void)
{
    u32 *list = *(u32 **)0x08AF2CCC;
    u32 *cur = (u32 *)list[2];
    u32 *p = scan_p;
    u32 base = 0;
    if (!p || p > cur || cur - p > 0x10000)
        p = cur;
    while (p < cur) {
        u32 w = *p, c = w >> 24;
        if (c == 0x10) {
            base = (w & 0x0F0000) << 8;
        } else if (c == 0x08) {
            u32 *t = (u32 *)(((u32)p & 0xF0000000) | base | (w & 0xFFFFFF));
            if (t > p && t <= cur) {
                p = t;
                continue;
            }
        } else if (c == 0x9C) {
            ccc43_cur_fbp = w & 0xFFFFFF;
        }
        p++;
    }
    scan_p = p;
}

/* Vertical shrink by S around pivot p (rounded to the nearest pixel). */
static int shrink_y_int(int y, int p)
{
    int d = (y - p) * S_NUM;
    return p + (d >= 0 ? (d + S_DEN / 2) / S_DEN : -((-d + S_DEN / 2) / S_DEN));
}

static void copy_bytes(u8 *dst, const u8 *src, u32 n)
{
    while (n--)
        *dst++ = *src++;
}

static u32 align_up(u32 v, u32 a)
{
    return (v + a - 1) & ~(a - 1);
}

static const u8 comp_size[4] = {0, 1, 2, 4};

/* Called from the sceGuDrawArray trampoline. Returns the vertex pointer to use. */
void *ccc43_draw(int prim, u32 vtype, int count, const void *indices, const void *verts)
{
    u32 tc, col, nrm, pos, wt, idx, wcount, morph;
    u32 off = 0, biggest = 1, sz, posoff, vsize, n, i;
    int minx = 0x7fffffff, maxx = -0x7fffffff, miny = 0x7fffffff, maxy = -0x7fffffff;
    int pv;
    u8 *dst;
    const u8 *src = (const u8 *)verts;

    (void)prim;
    if (!(vtype & 0x800000) || !verts || count <= 0)
        return (void *)verts;
    scan_list();
    if (!on_display())
        return (void *)verts;
    DBG(if (!dbg_done) dbg_emit());

    tc = vtype & 3;
    col = (vtype >> 2) & 7;
    nrm = (vtype >> 5) & 3;
    pos = (vtype >> 7) & 3;
    wt = (vtype >> 9) & 3;
    idx = (vtype >> 11) & 3;
    wcount = ((vtype >> 14) & 7) + 1;
    morph = ((vtype >> 18) & 7) + 1;
    if (morph != 1 || (pos != 2 && pos != 3))
        return (void *)verts;

    if (wt) { sz = comp_size[wt]; off = align_up(off, sz) + sz * wcount; if (sz > biggest) biggest = sz; }
    if (tc) { sz = comp_size[tc]; off = align_up(off, sz) + sz * 2; if (sz > biggest) biggest = sz; }
    if (col) { sz = (col == 7) ? 4 : 2; off = align_up(off, sz) + sz; if (sz > biggest) biggest = sz; }
    if (nrm) { sz = comp_size[nrm]; off = align_up(off, sz) + sz * 3; if (sz > biggest) biggest = sz; }
    sz = comp_size[pos];
    posoff = align_up(off, sz);
    off = posoff + sz * 3;
    if (sz > biggest) biggest = sz;
    vsize = align_up(off, biggest);

    /* number of vertices referenced */
    if (indices && idx) {
        n = 0;
        for (i = 0; i < (u32)count; i++) {
            u32 v = (idx == 1) ? ((const u8 *)indices)[i] : ((const u16 *)indices)[i];
            if (v + 1 > n) n = v + 1;
        }
    } else {
        n = (u32)count;
    }
    if (n == 0 || n > 4096)
        return (void *)verts;

    /* bounding box: skip full-screen draws */
    for (i = 0; i < n; i++) {
        const u8 *p = src + i * vsize + posoff;
        int x, y;
        if (pos == 2) {
            x = *(const s16 *)p;
            y = *(const s16 *)(p + 2);
        } else {
            x = (int)*(const float *)p;
            y = (int)*(const float *)(p + 4);
        }
        if (x < minx) minx = x;
        if (x > maxx) maxx = x;
        if (y < miny) miny = y;
        if (y > maxy) maxy = y;
    }
    /* Colourless textured s16 sprites (vtype 0x800102) are copies of off-screen
     * render targets (the composited 3D view, blur/dim buffers): not UI. */
    if ((vtype & 0xFFFFFF) == 0x800102)
        return (void *)verts;

    /* Track which parts of the screen the 2D layer covers. If the previous frame's
     * 2D covered (almost) the whole screen it is a menu / narration / load screen:
     * those are left exactly as the game draws them (full screen). */
    /* Large single draws (>= 1/8 of the screen) are tints, fades and backdrops, not UI
     * widgets (UI is built from small tiles, glyphs and strips): they are neither counted
     * nor shrunk, so they keep covering the whole screen behind a corrected dialogue box. */
    if ((maxx - minx) * (maxy - miny) >= SCREEN_W * SCREEN_H / 8)
        return (void *)verts;   /* backdrops, tints, fades: keep covering the screen */
    cover(minx, miny, maxx, maxy);
    if ((vtype & 0xFFFFFF) == 0x800182 && maxx - minx == 32 && maxy - miny == 32 && miny >= 150)
        box_tiles++;
    if (maxy - miny >= 200)
        tall_draws++;
    if (miny < CY && maxy > CY)
        straddle++;
    /* full-height strips (the narration panel fading over a dialogue box) are never shrunk */
    if (ccc43_mode == MODE_FULL || maxy - miny >= 200)
        return (void *)verts;
    if (ccc43_mode == MODE_DLG)
        pv = SCREEN_H;
    else if (ccc43_mode == MODE_HUDC)
        pv = CY;
    else
        pv = (miny + maxy >= SCREEN_H) ? SCREEN_H : 0;

    dst = (u8 *)sceGuGetMemory((int)(n * vsize));
    if (!dst)
        return (void *)verts;
    copy_bytes(dst, src, n * vsize);

    for (i = 0; i < n; i++) {
        u8 *p = dst + i * vsize + posoff;
        if (pos == 2) {
            s16 *py = (s16 *)(p + 2);
            *py = (s16)shrink_y_int(*py, pv);
        } else {
            float *py = (float *)(p + 4);
            *py = (float)pv + (*py - (float)pv) * S_F;
        }
    }
    return dst;
}

/* Replaces the jal to the internal scissor function inside sceGuScissor. */
TEXT2 void ccc43_scissor(void *ctx, int x, int y, int w, int h)
{
    scan_list();
    if (on_display() && (ccc43_mode & 1) && !(x <= 0 && y <= 0 && x + w >= SCREEN_W && y + h >= SCREEN_H)) {
        int pv = (ccc43_mode == MODE_DLG) ? SCREEN_H : CY;   /* dialogue or battle layer */
        int top = shrink_y_int(y, pv);
        int bot = shrink_y_int(y + h, pv);
        y = top;
        h = bot - top;
        if (h < 1) h = 1;
    }
    guScissorInternal(ctx, x, y, w, h);
}


/* Replaces the jal to the internal matrix upload inside sceGuSetMatrix. */
TEXT2 void ccc43_set_matrix(void *ctx, int type, const float *m)
{
    float mtx_copy[16];   /* the matrix is copied into the display list immediately */
    scan_list();
    if (type == 0 && m && on_display()) {
        copy_bytes((u8 *)mtx_copy, (const u8 *)m, sizeof(mtx_copy));
        if (mtx_copy[15] == 0.0f && mtx_copy[11] != 0.0f) {
            /* perspective */
            persp_frame = 1;
#ifdef CCC43_HOR_MINUS
            mtx_copy[0] *= (1.0f / S_F);
            mtx_copy[4] *= (1.0f / S_F);
            mtx_copy[8] *= (1.0f / S_F);
            mtx_copy[12] *= (1.0f / S_F);
#else
            mtx_copy[1] *= S_F;
            mtx_copy[5] *= S_F;
            mtx_copy[9] *= S_F;
            mtx_copy[13] *= S_F;
#endif
        }
        /* Orthographic projections are full-screen effects (flashes, overlays):
         * they are left alone so they keep covering the whole screen. */
        m = mtx_copy;
    }
    guSetMatrixInternal(ctx, type, m);
}





/* Mode switching. Entering dialogue takes one frame; leaving it waits 12 frames (box and
 * portrait are swapped between speakers) unless a narration panel or menu covers the screen.
 * HUD <-> full-screen UI switches after 2 agreeing frames (menus opening / closing). */
TEXT2 static void frame_end_classify(void)
{
    u32 c = classify(), target = c & 0xFF, need;
    if (target == ccc43_mode) {
        ccc43_switch = 0;
        return;
    }
    if (target == MODE_DLG || (c & 0x100))
        need = 1;
    else if (ccc43_mode == MODE_DLG)
        need = 12;
    else if (target == MODE_FULL)
        need = 2;
    else
        need = 2;
    if (++ccc43_switch >= need) {
        ccc43_mode = target;
        ccc43_switch = 0;
        DBG(dbg_snap = (dbg_snap + 0x1000) & 0xFF000 | (dbg_hist & 0xFFF));
    }
}

typedef int (*DisplaySetFrameBufFn)(void *topaddr, int bufferwidth, int pixelformat, int sync);
#define sceDisplaySetFrameBuf ((DisplaySetFrameBufFn)0x089A68F4)   /* import stub */

/* Replaces the jal to sceDisplaySetFrameBuf inside libgu's swap/display functions:
 * called exactly once per displayed frame, so the frame that was just finished is
 * classified here, and drawing restarts on a display buffer. */
TEXT2 int ccc43_frame_end(void *topaddr, int bufferwidth, int pixelformat, int sync)
{
    frame_end_classify();
    ccc43_cur_fbp = 0;
    scan_p = 0;
    DBG(dbg_done = 0);
    return sceDisplaySetFrameBuf(topaddr, bufferwidth, pixelformat, sync);
}
