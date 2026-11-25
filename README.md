# Fate/Extra CCC 4:3 patch

A 4:3 display patch for **Fate/Extra CCC** (PSP, NPJH50505), for playing on a 4:3 screen
(CRT, 4:3 monitor) with correct proportions. It patches the game's code (EBOOT), so it
works the same on any emulator or on hardware, with no emulator settings needed.

Works with the **English fan translation v1.0** and with the original **Japanese** release.

## What it changes

| Screen | Result |
|---|---|
| 3D (field, dungeon, battle, cutscenes) | Correct 4:3 proportions, nothing cropped: you see a bit more above and below (Vert+) |
| Dialogue scenes | Dialogue box and character portraits in correct proportions, kept at the bottom of the screen |
| Dungeon HUD | Correct proportions; every element stays at its own screen edge |
| Menus, narration, save/load, shop, battle HUD, results | Left exactly as the game draws them (stretched to fill the screen, like the original) |

Set your emulator / output to **4:3 stretch** (in PPSSPP: *Display layout & effects* →
stretch to fill, on a 4:3 display or window).

## Install

You need [xdelta3](https://github.com/jmacd/xdelta-gpl/releases) or a GUI for it
(e.g. *Delta Patcher*). Patches are in [`release/`](release/).

### English (fan translation v1.0) — ISO

1. Patch your English v1.0 ISO with `release/ccc-4x3-en-iso.xdelta`:
   ```
   xdelta3 -d -s "Fate Extra CCC (English v1.0).iso" ccc-4x3-en-iso.xdelta "Fate Extra CCC (English v1.0) 4x3.iso"
   ```
2. Play the new ISO.

Expected input ISO: SHA-1 `e2dcbc423ff939297a6a9ccb159cbb6ccaefb88c` (CRC32 `A5042E68`).
Output ISO: SHA-1 `11f88865b0925e0d29d084b6bf8ff84aec4e6041`.

If you play the English version as an extracted folder instead, patch
`PSP_GAME/SYSDIR/EBOOT.BIN` with `release/ccc-4x3-en-eboot.xdelta`
(input SHA-1 `64773d23a233cc7c86a222714b8516be91f5871a`).

### Japanese — EBOOT

The Japanese ISO's EBOOT is encrypted, so the patch applies to the decrypted EBOOT:

1. Get the decrypted EBOOT: in PPSSPP enable *Settings → Tools → Developer tools →
   Dump decrypted EBOOT.BIN on game boot*, start the game once, and take
   `memstick/PSP/SYSTEM/DUMP/NPJH50505_EBOOT.BIN`.
   Expected SHA-1 `ea74f1ccea0b42c416930a92781ad42ae6603a99`.
2. Patch it with `release/ccc-4x3-jp-eboot.xdelta` → `EBOOT.BIN`
   (output SHA-1 `79d7814a12bc04c14c549cf99bffe74016709d51`).
3. Put it in the game as `PSP_GAME/SYSDIR/EBOOT.BIN`: either in an extracted copy of the
   game, or into the ISO with UMD-replace, or with the script in this repo:
   ```
   python3 tools/iso_replace.py original.iso patched.iso PSP_GAME/SYSDIR/EBOOT.BIN EBOOT.BIN
   ```

### Real PSP

The patched game uses a decrypted EBOOT, which custom firmware runs from an ISO. Tested on
PPSSPP so far; reports from hardware are welcome.

## How it works

The game links Sony's `libgu` statically. The patch hooks its draw, matrix, scissor and
display-swap functions and adds about 3 KB of code to the EBOOT (no change to the game's
memory layout, which the English translation relies on):

- **3D:** perspective projection matrices get their vertical scale multiplied by
  `(4/3) / (480/272) = 34/45`.
- **2D:** each frame is classified from what the previous frame drew (where the 2D layer
  covers the screen, the dialogue box's 32×32 tiles, full-height narration panels, whether
  3D is on screen) as *dialogue*, *dungeon HUD* or *full-screen UI*; vertices of 2D draws are
  scaled by 34/45 towards the bottom edge (dialogue), towards their nearest edge (HUD), or
  left alone.

Details, addresses and the reasoning behind each rule are in [`docs/DEVLOG.md`](docs/DEVLOG.md).

## Building

Needs `mips-linux-gnu-gcc` / binutils and Python 3, plus your own decrypted EBOOT
(not included: no game data is stored in this repository).

```
python3 patch/build.py <decrypted EBOOT> EBOOT_43.BIN            # release build
python3 patch/build.py <decrypted EBOOT> EBOOT_43.BIN --debug    # writes classifier state into frame dumps
python3 patch/build.py <decrypted EBOOT> EBOOT_43.BIN --hor-minus # 3D: crop the sides instead (Hor-)
```

`tools/gedump.py` and `tools/classify_dumps.py` read PPSSPP GE frame dumps (`.ppdmp`) to
inspect draws and replay the classifier.
