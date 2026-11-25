# 4:3 patch design

Target: a CRT / 4:3 display showing the PSP's 480x272 framebuffer stretched to 4:3.
The display squeezes everything horizontally by s = (4/3) / (480/272) = 0.7556.

## Key finding
The game draws through Sony's libgu, statically linked at ~0x08996000. Every draw,
scissor and matrix upload goes through three functions, so the patch can be a few
hooks instead of hundreds of per-menu edits:

| function | address | patch |
|---|---|---|
| sceGuDrawArray / DrawArrayN | 0x08996ABC / 0x08996B8C | through-mode (vtype & 0x800000): copy vertices, y' = 136 + (y - 136) * s |
| sceGuScissor | 0x08997548 | same y transform on the rectangle |
| sceGuSetMatrix | 0x08996A90 | type 0 (projection): perspective -> 3D fix; orthographic -> UI y-shrink |

## 3D (perspective projection, m[11] == -1, m[15] == 0)
- Vert+ (default): m[5] *= s  -> same horizontal view, more visible vertically
- Hor- (option):   m[0] /= s  -> same vertical view, sides cropped

## 2D UI (through mode)
- Shrink Y around the screen centre so proportions are correct after the display squeeze.
- Copy vertices into fresh GE memory (sceGuGetMemory) instead of editing in place:
  static vertex buffers would otherwise shrink again every frame.
- Position offset inside a vertex depends on vtype (weights, texture, colour, normal, position).
- Indexed draws: copy up to the highest index used.

## Exceptions (to verify in-game)
- Full-screen quads/scissors (0,0)-(480,272): backgrounds, fades, clears -> leave untouched.
  ~35 call sites pass 480/272 literally.
- Draws into off-screen render targets (UI composition) -> leave untouched; needs the
  current draw buffer (sceGuDrawBuffer / GE FBP) — not yet located.
- 2D elements positioned from 3D world positions (markers, name tags) may need the
  same projection correction applied in the game's own projection math.

## Implementation
Native C code (homebrew PSP SDK) injected like the translation patch, plus jumps at
the three function entries. Must not overlap the translation's injected region
(after PRELOAD.pak, ~0x08D5F0F0+). Ship as xdelta against the JP and EN EBOOTs.
