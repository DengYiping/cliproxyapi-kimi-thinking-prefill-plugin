"""Naive PE parser: trusts every on-disk count/offset. For diff study only."""
import struct


def parse(buf):
    lfanew = struct.unpack_from("<I", buf, 0x3C)[0]
    nsec = struct.unpack_from("<H", buf, lfanew + 6)[0]
    optsize = struct.unpack_from("<H", buf, lfanew + 20)[0]
    oh = lfanew + 24
    image_base = struct.unpack_from("<Q", buf, oh + 24)[0]
    rel_rva, rel_size = struct.unpack_from("<II", buf, oh + 152)
    sh = oh + optsize
    sections = []
    for i in range(nsec):
        name = bytes(buf[sh + 40 * i:sh + 40 * i + 8]).rstrip(b"\0").decode()
        vsize, va, rawsize, rawptr = struct.unpack_from("<IIII", buf,
                                                        sh + 40 * i + 8)
        sections.append(dict(name=name, vsize=vsize, va=va,
                             rawsize=rawsize, rawptr=rawptr))
    relocs = []
    if rel_rva:
        s = next(s for s in sections
                 if s["va"] <= rel_rva < s["va"] + s["rawsize"])
        off = s["rawptr"] + rel_rva - s["va"]
        end = off + rel_size
        while off < end:
            bva, bsz = struct.unpack_from("<II", buf, off)
            for j in range((bsz - 8) // 2):
                e = struct.unpack_from("<H", buf, off + 8 + 2 * j)[0]
                relocs.append(dict(block_rva=bva, type=e >> 12,
                                   offset=e & 0xFFF))
            off += bsz
    return dict(image_base=image_base, sections=sections, relocs=relocs)
