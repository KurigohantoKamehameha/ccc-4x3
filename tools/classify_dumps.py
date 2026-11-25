#!/usr/bin/env python3
"""Replay the patch's frame classification on PPSSPP frame dumps (regression check).

usage: classify_dumps.py DUMP[:PIVOT] ...
PIVOT is the y the 2D layer was shrunk around when the dump was recorded
(272 = bottom, 0 = untouched) so coordinates can be restored. Dumps from build 18 on carry
the patch's own state (debug NOPs), printed as well.
Keep in sync with classify()/ccc43_draw() in patch/ccc43.c.
"""
import sys

from gedump import draws

S = 34 / 45


def classify(path, pivot):
    rows, tiles, tall, straddle, persp, dbg = [0] * 17, 0, 0, 0, False, []
    for d in draws(path):
        if 'nop' in d:
            dbg.append(d['nop'])
            continue
        if (d['fb'] & 0x1FFFFF) >= 0x88000:
            continue
        if not d['through']:
            persp = True          # approximation: transformed draws on the display
            continue
        if not d['bbox'] or d['i'] == 0 or d['vtype'] & 0xFFFFFF == 0x800102:
            continue
        x0, y0, x1, y1 = d['bbox']
        if pivot and y1 - y0 < 200 * S:
            y0, y1 = pivot + (y0 - pivot) / S, pivot + (y1 - pivot) / S
        if (x1 - x0) * (y1 - y0) >= 480 * 272 / 8:      # tints, fades, backdrops
            continue
        if d['vtype'] & 0xFFFFFF == 0x800182 and round(x1 - x0) == 32 and round(y1 - y0) == 32 and y0 >= 150:
            tiles += 1
        if y1 - y0 >= 200:
            tall += 1
        if y0 < 136 < y1:
            straddle += 1
        x0, x1 = max(0, int(x0)), min(480, int(x1))
        y0, y1 = max(0, int(y0)), min(272, int(y1))
        if x1 <= x0 or y1 <= y0:
            continue
        for r in range(y0 >> 4, ((y1 - 1) >> 4) + 1):
            for c in range(x0 >> 4, ((x1 - 1) >> 4) + 1):
                rows[r] |= 1 << c
    bottom = [bin(rows[r]).count('1') for r in range(12, 16)]
    top = sum(bin(rows[r]).count('1') for r in range(10))
    dlg = all(b >= 29 for b in bottom) and 40 <= tiles < 150 and (top < 210 or tall >= 8)
    total = sum(bin(r).count('1') for r in rows)
    hud = persp and total < 510 * 7 // 10 and tall < 8
    sep = straddle <= 2 and not (rows[8] & rows[9])
    mode = 'DIALOGUE' if dlg else 'HUD' if hud and sep else 'full'
    return mode, bottom, top, tiles, tall, straddle, dbg


if __name__ == '__main__':
    for arg in sys.argv[1:]:
        path, _, piv = arg.partition(':')
        mode, bottom, top, tiles, tall, straddle, dbg = classify(path, int(piv or 0))
        print('%-24s %-9s bottom=%s top=%d tiles=%d tall=%d straddle=%d%s' % (
            path.split('/')[-1], mode, bottom, top, tiles, tall, straddle,
            ' dbg=' + ','.join('%06X' % a for a in dbg) if dbg else ''))
