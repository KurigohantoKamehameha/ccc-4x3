# Fate/Extra CCC (NPJH50505) — RE notes

## Binaries (bin/, never commit)
- jp_dump.bin  — PPSSPP-decrypted JP EBOOT, sha1 ea74f1ccea0b42c416930a92781ad42ae6603a99
- en_eboot.bin — English v1.0 EBOOT (plain ELF), sha1 64773d23a233cc7c86a222714b8516be91f5871a
- en_boot.bin  — BOOT.BIN from EN ISO (zero-filled dummy)

## Layout
- PRX (type 0xFFA0), module name FATE_MAIN, load base in PPSSPP 0x08804000
- .text 0x08804000–0x089A67AC (0x1A27AC bytes), ~6.2k jal targets (+ indirect/virtual)
- 721 VFPU instructions only; section names/symbols stripped
- Engine: Imageepoch "IePSPlib" (C++), CRI middleware (CRI FS 2.56, built "GCC3003 SCE06060010")
- Game compiler: TBD (CRI libs are GCC-based; game code not yet fingerprinted)

## JP vs EN
- Only 231 diff runs / 4751 bytes in loaded segment -> EN = small boot hooks;
  main EN code injected at runtime after PRELOAD.pak (~0x08D5F0F0+, see ccc-tl/translation-tools)

## Known functions (JP addresses, confirmed as jal targets)
- 0x088E7C28 text renderer (GameDrawText)
- 0x088EBBD4 formatted text draw
- 0x088BA4D8 text width measure
- 0x0898CF24 memcpy, 0x0898CE90 memcmp, 0x0898D4A0 strcmp, 0x0898D518 strlen, 0x0898D4D4 strcpy

## 2D library region (ie2d) ~0x088E0000–0x088F3000
- 0x088EDDCC refs ie2d_prim_filter_psp.cpp
- 0x088F19F4 refs ie2d_texbnk_psp.cpp
- 3D: IePSPModel.cpp 0x088FB440, ie3d_shadow.cpp 0x088F9A0C
- main.cpp ref 0x0896C4C4

## Next
- Find libgu (sceGuDrawArray / sceGuScissor) statically linked; trace 2D through-mode draws from ie2d
- Find projection setup (sceGumPerspective-like / proj matrix upload) for 3D aspect
- Compiler fingerprint

## Session 2 (2026-11-25)
- Imports parsed (202 functions, all named via PPSSPP NID table: tools/data/nids.json).
- libgu is statically linked at ~0x08996000; sceGuDrawArray 0x08996ABC, sceGuScissor 0x08997548,
  sceGuSetMatrix 0x08996A90. Only 54 DrawArray call sites; through-mode ones are in ie2d.
- Camera: hfov->vfov uses 480/272 at 0x088F2740; viewport 480x272 stored in camera object.
- EN patch does NOT modify libgu or camera code -> same hook addresses work for JP and EN.
  EN does patch ~31 words in ie2d text drawing (expected).
- Note: PRX relocations use segment-relative values (hi/lo pairs into BSS are relative to 0x229600);
  data addresses need the relocation table to resolve properly (TODO in tools/prx.py).
- Design: docs/4x3-design.md. Symbols: symbols/jp.txt.

## Session 3: frame dump findings (tools/gedump.py)
- Servant select: the moving blue backdrop is 3D (84 perspective draws into the display fb);
  the green menu is a 15x9 grid of 32x32 RAM-texture tiles covering the full screen.
- Narration window: background is a VRAM texture (0x040Exxxx) = copy of the rendered screen,
  drawn in strips; shrinking it misaligned it (the "black bar"). UI is also composed in
  off-screen targets (fb 0xCC000/0xCD000/0xD4000/0xD6000/0xAA000/0x88000).
- Display buffers: VRAM 0x00000 and 0x44000 (512 stride). sceGuDrawBufferList = 0x089968A0 (19 callers).
- Build 4 rules: only touch draws on the display; never shrink VRAM-texture copies; untextured
  full-screen = fade (skip); 3D frames anchor the UI to the bottom unless the previous frame was a
  full-screen 2D menu (>=90% RAM-textured coverage) -> centre.
- Build 5 (user chose "option B"): screens whose 2D layer covers >=80% of a 30x17 grid of
  16px cells (previous frame) are left untouched (menus, narration, load, name entry);
  partial UI over 3D (dialogue) is shrunk towards the bottom. Load screen draws partly bypass
  libgu (direct GE writes), another reason to leave full-screen UI alone.
- ie2d texture tracking (0x088F0EB4) misses some binds: narration strips use VRAM 0x040Exxxx
  but last_tex was stale. Not critical under option B.
- Dumps 6-9: every scene has one colourless s16 sprite (vtype 0x800102, tex 0x040Cxxxx) = copy of
  an off-screen render target over the whole screen; counting it made dialogue scenes look
  "full-screen UI" (Issei unshrunk). Build 6 ignores it. The boot "yellow flash" is drawn with an
  orthographic projection -> ortho matrices are no longer shrunk.
- Build 8: battle HUD was shrunk towards the bottom (top HP bars ended mid-screen). Logic inverted:
  2D is left untouched by default; only frames classified as dialogue (rows 12-15 covered across
  >=24/30 cells AND rows 0-9 <70% covered) are shrunk, bottom-anchored. Simulated on dumps 1-9:
  only the two dialogue dumps (6, 9) classify as dialogue.
- Dumps 10-14 (Jinako dialogue, dungeon x3, battle). Battle has ~100 32x32 tiles and rows 12-15
  covered 23-25/30; dialogue boxes cover 30/30 in rows 11-16. Build 10 requires >= 29.
- NOTE: PPSSPP savestates contain RAM, i.e. the patch code at load time. Loading an older state
  runs the old build. Always boot fresh when testing a new EBOOT.
- Dump 15 (Kiara): six untextured 160x136 quads tile the whole screen (a colour tint) and made the
  dialogue look like full-screen UI. Build 11 ignores any single draw >= 1/8 of the screen for
  coverage. tools/classify_dumps.py replays the detection; all 15 dumps classify correctly.
- Dump 16 (Sakura, flickering) classifies as dialogue, so the flicker came from *when* frames were
  classified: colour clears also happen in off-screen targets the fbp tracking can miss, which
  classified half-drawn frames. Build 12 classifies once per displayed frame by hooking libgu's
  three jal sceDisplaySetFrameBuf (0x089961E4, 0x089962AC, 0x089967E8) and resets fbp there.
- Dump 17 (flicker, build 12): frame classifies as dialogue but nothing was adjusted -> the
  patch thought it was still drawing off-screen. The game returns to the display by starting a
  new GE list (libgu start 0x08995C68, re-emits the context draw buffer), not via
  sceGuDrawBufferList. Build 13 hooks the 4 calls to it (reset fbp to display) and the single
  sceGuDrawBuffer call (0x089962CC at 0x088E2D40).
- Dumps 18-19 (build 13, still flickering): both frames classify as dialogue offline but were left
  untouched in-game -> the in-game state differs from the offline model. Build 14 adds a debug
  channel: at the first 2D draw of each frame the patch writes 3 GE NOPs (0xA..., 0xB..., 0xC...)
  with fbp/on_display/mode/switch/last result, bottom-row min, tile count and top coverage;
  tools/gedump.py prints them as "DBG".
- Space: hook code hit the 0x08B70000 limit. Zero-initialised variables now live in 184 bytes of
  engine assert path strings at 0x089BE420 (no relocations there, zeroed by build.py); the clear
  hook and frame_3d flag were removed (unused since build 8).
- Dumps 20-24 (build 14 debug NOPs): mode = dialogue, classification stable (switch 0), but the
  patch believed it was still on an off-screen target (fbp 0xD6000) when the UI was drawn.
  The return to the display (GE seq: 3E/3F proj, 3C/3D view, 42-46 viewport, D2/9D/9C, D4/D5,
  15/16, 9E/9F, 4C/4D) is written directly by game code (its own GE command helpers around
  0x0896B3xx), not through libgu. Build 15 reads FBP (0x9C) commands from the current display
  list since the last hook call instead (skipping sceGuGetMemory BASE+JUMP blocks); the
  DrawBufferList/list-start/DrawBuffer call-site hooks and ie2d texture tracking were removed.
- Dumps 25-27 (speaker change): captured frames are correct (DBG A00012: on display, dialogue mode,
  last = dialogue). The flicker is the box/portrait swap between speakers making a few frames not
  look like dialogue. Build 16: leaving dialogue needs 20 frames unless the screen is clearly
  full-screen UI (top coverage >= 70%), then 2. Debug NOP channel removed again (space).
- Dead End screen (build 16): a black full-screen backdrop drawn behind the dialogue box was shrunk
  with the box, leaving a band of the previous scene at the top. Build 17: single draws >= 1/8 of
  the screen are never shrunk (and never counted).

## Build 18 (diagnostic)
- Report on build 17: flicker when the speaking character changes. Dump 28 was a full-screen
  narration panel (15 full-height strips + text, top=300): correctly left untouched; no flicker
  frame captured. The large draws in dialogue dumps are only the 6x 160x136 untextured tints, so
  build 17's "never shrink large draws" rule does not touch portraits.
- Leaving dialogue mode without clear full-screen UI now waits 45 frames (was 20).
- Debug NOPs are back (real GE NOPs, command 0x00): payload 0xA = last 20 frames of the dialogue
  test, 0xB = full_ui/switch/bottom_ok/top, 0xC = box tiles. `tools/gedump.py` decodes them, so a
  dump taken during a flicker shows which test failed and for how long.
- Lesson: debug words must use command 0x00; 0x0A/0x0B/0x0C are CALL/RET/END.
- Freed space: removed the untextured full-screen check in ccc43_draw (covered by the 1/8 rule).

## Build 19 (diagnostic)
- Dumps 29-34 (build 17, dungeon dialogue with Gilgamesh) are all stable dialogue frames
  (bottom 30x4, top 76-87, tiles 89-91 after un-shrinking): the flicker frame itself is not captured.
- Measured from the user's screenshots: dialogue text is 0.76x the height of the stretched
  dungeon "NEXT" bar text, as designed; the dungeon HUD (stats, floor, minimap) is not shrunk in
  dialogue mode either, so dialogue box and HUD now differ in proportions in the same frame.
- Every frame now also carries NOP 0xD: number of mode switches so far plus the test history at the
  last switch. A dump taken any time after a flicker shows whether the mode actually switched; if
  the count did not change, the stretched frame came from render-target tracking (on_display), not
  from the classifier.
- Space: removed ccc43_enabled and turned ccc43_full_ui into the zero-initialised ccc43_dialogue
  (no .data section any more); dropped the tile-count NOP (tiles_ok is a bit in NOP 0xB).

## Build 20: narration transitions, dungeon HUD correction
- Build 19 dumps 35-38: the mode counter went 33 -> 35 between two dialogue frames and the
  history at the last switch was ...0000000011, i.e. the scene left dialogue for >= 10 frames.
  Dumps 30/37 show why: narration lines (full-screen panel of 17 full-height strips, text typing
  out) sit between the characters' lines. The "flicker" is the box and portrait drawn stretched
  while the panel fades in/out over them.
- Dialogue test is now: bottom rows covered, 40 <= box tiles < 150, and (top < 210 or >= 8
  full-height strips). So a panel fading over a box keeps dialogue mode, and full-height strips
  are never shrunk. Entering dialogue takes 1 frame, leaving it 12 (1 when a panel/menu covers
  the screen).
- New MODE_HUD: perspective frame, top < 210, <= 2 draws crossing y=136 and no overlap of grid rows
  8 and 9 (nothing spans the middle). Each draw is shrunk towards the edge its centre is nearest
  to (pivot 0 or 272). Dungeon (dumps 11/13) -> HUD; battle (4, 12, 14) stays untouched.
- Code space: functions marked TEXT2 go over 1520 bytes of CRI FS error strings at 0x08A21B18
  (identical in JP and EN, no relocations inside). tools/ge3d.py lists transformed draws with
  their screen-space bbox (written while looking for the HUD: it is through-mode 2D).

## Build 21
- HUD after a menu closes: switch full -> HUD after 2 frames (was 6); the user saw a short stretched flash.

## Build 22: battle HUD
- Battle dumps 40-43 (build 21: mode full): HP bars across the top, a large command/card grid
  (y 60-260) on the right, a cluster bottom-left, banners across the middle (43). Result grid (44)
  covers 86%.
- HUD frames are now any perspective frame with < 70% 2D coverage and no narration panel.
  Separable layouts (nothing across y=136: dungeon) keep per-draw edge anchoring (MODE_HUD);
  otherwise MODE_HUDC shrinks the whole layer around y=136 (scissors too).
- Tried and rejected (simulated on the dumps): grouping draws by the connected run / connected
  component of the previous frame's 16px grid. Battle elements touch each other in the grid, so
  components merge (top band + command grid) or one panel gets two pivots and tears apart.

## Build 23
- User preferred the battle HUD stretched (as drawn): non-separable HUD frames go to MODE_FULL again.
  MODE_HUDC code stays (unused) in case it is wanted later.
