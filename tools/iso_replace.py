#!/usr/bin/env python3
"""Replace one file inside an ISO 9660 image (PSP UMD ISO) without rebuilding it.

usage: iso_replace.py IN_ISO OUT_ISO ISO_PATH NEW_FILE
  e.g. iso_replace.py game.iso game_43.iso PSP_GAME/SYSDIR/EBOOT.BIN EBOOT_43.BIN

If the new file fits in the old file's sectors it is written in place; otherwise it is
appended at the end of the image. Both copies of the directory record (little and big
endian extent/size) and the volume space size are updated. Everything else is copied
byte for byte, so the output differs from the input only where needed (small xdelta).
"""
import shutil
import struct
import sys

SECTOR = 2048


def read_sector(f, lba, n=1):
    f.seek(lba * SECTOR)
    return f.read(n * SECTOR)


def find_record(f, root_lba, root_size, parts):
    lba, size = root_lba, root_size
    for depth, name in enumerate(parts):
        data = read_sector(f, lba, (size + SECTOR - 1) // SECTOR)
        pos, found = 0, None
        while pos < len(data):
            rlen = data[pos]
            if rlen == 0:                       # records never cross sectors
                pos = (pos // SECTOR + 1) * SECTOR
                continue
            ident = data[pos + 33:pos + 33 + data[pos + 32]].decode('ascii', 'replace').split(';')[0]
            if ident.upper() == name.upper():
                found = (lba * SECTOR + pos, data[pos:pos + rlen])
                break
            pos += rlen
        if not found:
            sys.exit('not found in ISO: ' + '/'.join(parts[:depth + 1]))
        off, rec = found
        lba, size = struct.unpack_from('<I', rec, 2)[0], struct.unpack_from('<I', rec, 10)[0]
    return off, lba, size


def main(in_iso, out_iso, iso_path, new_file):
    new = open(new_file, 'rb').read()
    shutil.copyfile(in_iso, out_iso)
    with open(out_iso, 'r+b') as f:
        pvd = read_sector(f, 16)
        assert pvd[1:6] == b'CD001' and pvd[0] == 1, 'no primary volume descriptor'
        root = pvd[156:156 + 34]
        rec_off, lba, size = find_record(f, struct.unpack_from('<I', root, 2)[0],
                                         struct.unpack_from('<I', root, 10)[0], iso_path.strip('/').split('/'))
        old_sectors = (size + SECTOR - 1) // SECTOR
        new_sectors = (len(new) + SECTOR - 1) // SECTOR
        f.seek(0, 2)
        total = f.tell() // SECTOR
        if new_sectors <= old_sectors:
            new_lba = lba
            f.seek(lba * SECTOR)
            f.write(new + bytes(old_sectors * SECTOR - len(new)))
        else:
            new_lba = total
            f.seek(new_lba * SECTOR)
            f.write(new + bytes(new_sectors * SECTOR - len(new)))
            total = new_lba + new_sectors
            f.seek(16 * SECTOR + 80)                    # volume space size (both-endian)
            f.write(struct.pack('<I', total) + struct.pack('>I', total))
        f.seek(rec_off + 2)
        f.write(struct.pack('<I', new_lba) + struct.pack('>I', new_lba)
                + struct.pack('<I', len(new)) + struct.pack('>I', len(new)))
    print('%s: %s at LBA %d (%d bytes, was LBA %d, %d bytes)%s' % (
        out_iso, iso_path, new_lba, len(new), lba, size, '' if new_lba == lba else ', appended'))


if __name__ == '__main__':
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    main(*sys.argv[1:])
