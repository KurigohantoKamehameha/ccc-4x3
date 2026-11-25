#!/usr/bin/env python3
"""List transformed (non-through) draws with their projection kind and screen-space bbox.

usage: ge3d.py DUMP [--ortho]
"""
import struct
import sys

from gedump import read_dump, vertex_layout, CT_VERTICES, CT_REGISTERS


def f24(a):
    return struct.unpack('<f', struct.pack('<I', (a & 0xFFFFFF) << 8))[0]


def mat_mul4(v, m):  # row vector * 4x4 (m as list of 16, row-major rows)
    return [sum(v[k] * m[k * 4 + j] for k in range(4)) for j in range(4)]


def positions3(blob, vtype, n):
    posoff, vsize, pos = vertex_layout(vtype)
    out = []
    for i in range(n):
        o = i * vsize + posoff
        if pos == 3 and o + 12 <= len(blob):
            out.append(struct.unpack_from('<fff', blob, o))
        elif pos == 2 and o + 6 <= len(blob):
            x, y, z = struct.unpack_from('<hhh', blob, o)
            out.append((x / 32768, y / 32768, z / 32768))
        elif pos == 1 and o + 3 <= len(blob):
            x, y, z = struct.unpack_from('<bbb', blob, o)
            out.append((x / 128, y / 128, z / 128))
    return out


def run(path, only_ortho):
    _, cmds, buf = read_dump(path)
    world = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]
    view = list(world)
    proj = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    wi = vi = pi = 0
    vp = {}
    st = {'vtype': 0, 'fbp': 0, 'tbp': 0}
    verts = b''
    n = 0
    for typ, sz, ptr in cmds:
        if typ == CT_VERTICES:
            verts = buf[ptr:ptr + sz]
            continue
        if typ != CT_REGISTERS:
            continue
        for i in range(sz // 4):
            w = struct.unpack_from('<I', buf, ptr + 4 * i)[0]
            c, a = w >> 24, w & 0xFFFFFF
            if c == 0x3A: wi = a & 15
            elif c == 0x3B:
                if wi < 12: world[wi] = f24(a)
                wi += 1
            elif c == 0x3C: vi = a & 15
            elif c == 0x3D:
                if vi < 12: view[vi] = f24(a)
                vi += 1
            elif c == 0x3E: pi = a & 15
            elif c == 0x3F:
                if pi < 16: proj[pi] = f24(a)
                pi += 1
            elif 0x42 <= c <= 0x47: vp[c] = f24(a)
            elif c == 0x4C: vp['ox'] = (a & 0xFFFF) / 16
            elif c == 0x4D: vp['oy'] = (a & 0xFFFF) / 16
            elif c == 0x12: st['vtype'] = a
            elif c == 0x9C: st['fbp'] = a
            elif c == 0xA0: st['tbp'] = a
            elif c == 0x04:
                vt = st['vtype']
                count = a & 0xFFFF
                idx = n
                n += 1
                if vt & 0x800000 or (st['fbp'] & 0x1FFFFF) >= 0x88000:
                    continue
                ortho = proj[15] != 0 and proj[11] == 0
                if only_ortho and not ortho:
                    continue
                W = [world[0], world[1], world[2], 0, world[3], world[4], world[5], 0,
                     world[6], world[7], world[8], 0, world[9], world[10], world[11], 1]
                V = [view[0], view[1], view[2], 0, view[3], view[4], view[5], 0,
                     view[6], view[7], view[8], 0, view[9], view[10], view[11], 1]
                xs, ys = [], []
                for p in positions3(verts, vt, count):
                    v = mat_mul4(mat_mul4(mat_mul4([p[0], p[1], p[2], 1], W), V), proj)
                    if v[3] == 0:
                        continue
                    sx = vp.get(0x45, 2048) + vp.get(0x42, 240) * v[0] / v[3] - vp.get('ox', 1808)
                    sy = vp.get(0x46, 2048) + vp.get(0x43, -136) * v[1] / v[3] - vp.get('oy', 1912)
                    xs.append(sx); ys.append(sy)
                if not xs:
                    continue
                print('%4d prim=%d n=%-3d vt=%06X %s tex=%06X (%6.1f,%6.1f)-(%6.1f,%6.1f) wt=(%.1f,%.1f)' % (
                    idx, (a >> 16) & 7, count, vt, 'ORTHO' if ortho else 'persp', st['tbp'],
                    min(xs), min(ys), max(xs), max(ys), world[9], world[10]))


if __name__ == '__main__':
    run(sys.argv[1], '--ortho' in sys.argv)
