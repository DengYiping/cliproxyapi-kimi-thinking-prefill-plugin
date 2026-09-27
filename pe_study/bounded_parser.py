"""Bounded PE64 parser + relocator. Standard library only (struct)."""
import struct


class PEError(Exception):
    pass


MAX_SECTIONS = 96          # PE spec practical limit
MAX_DIRS = 16              # NumberOfRvaAndSizes cap
MAX_RELOC_ENTRIES = 0x10000


def _need(buf, off, size, what):
    if off < 0 or size < 0 or off + size > len(buf):
        raise PEError(f"{what}: [{off:#x},{off + size:#x}) outside "
                      f"{len(buf):#x}-byte image")


def _rd(buf, off, fmt, what):
    size = struct.calcsize(fmt)
    _need(buf, off, size, what)
    return struct.unpack_from(fmt, buf, off)[0]


def u16(b, o): return _rd(b, o, "<H", "u16")
def u32(b, o): return _rd(b, o, "<I", "u32")
def u64(b, o): return _rd(b, o, "<Q", "u64")


def parse(buf):
    if u16(buf, 0) != 0x5A4D:
        raise PEError("bad e_magic")
    lfanew = u32(buf, 0x3C)
    _need(buf, lfanew, 24, "PE signature + file header")
    if u32(buf, lfanew) != 0x4550:
        raise PEError("bad PE signature")
    fh = lfanew + 4
    machine, nsec = u16(buf, fh), u16(buf, fh + 2)
    optsize = u16(buf, fh + 16)
    if not 0 < nsec <= MAX_SECTIONS:
        raise PEError(f"implausible section count {nsec}")
    oh = fh + 20
    _need(buf, oh, optsize, "optional header")
    if u16(buf, oh) != 0x20B:
        raise PEError("not PE32+")
    image_base = u64(buf, oh + 24)
    n_dirs = u32(buf, oh + 108)
    if n_dirs > MAX_DIRS:
        raise PEError(f"implausible dir count {n_dirs}")
    rel_rva = rel_size = 0
    if n_dirs > 5:
        _need(buf, oh + 112 + 5 * 8, 8, "reloc directory entry")
        rel_rva, rel_size = u32(buf, oh + 152), u32(buf, oh + 156)
    sh = oh + optsize
    sections = []
    for i in range(nsec):
        _need(buf, sh + 40 * i, 40, f"section header {i}")
        name = bytes(buf[sh + 40 * i:sh + 40 * i + 8]).rstrip(b"\0")
        name = name.decode("ascii", "replace")
        vsize, va, rawsize, rawptr = struct.unpack_from(
            "<IIII", buf, sh + 40 * i + 8)
        if rawsize:
            _need(buf, rawptr, rawsize, f"raw data {name}")
        sections.append(dict(name=name, vsize=vsize, va=va,
                             rawsize=rawsize, rawptr=rawptr))
    relocs = parse_relocs(buf, sections, rel_rva, rel_size)
    return dict(machine=machine, image_base=image_base,
                sections=sections, relocs=relocs)


def rva_to_off(sections, rva):
    for s in sections:
        span = max(s["vsize"], s["rawsize"])
        if s["va"] <= rva < s["va"] + span:
            return s["rawptr"] + (rva - s["va"])
    raise PEError(f"RVA {rva:#x} not mapped by any section")


def parse_relocs(buf, sections, rva, size):
    out = []
    if not rva:
        return out
    base = rva_to_off(sections, rva)
    _need(buf, base, size, "reloc directory")
    off, end = base, base + size
    while off < end:
        bva, bsz = u32(buf, off), u32(buf, off + 4)
        if bsz < 8 or off + bsz > end:
            raise PEError(f"bad SizeOfBlock {bsz:#x} @ {off:#x}")
        n = (bsz - 8) // 2
        if len(out) + n > MAX_RELOC_ENTRIES:
            raise PEError("reloc entry cap exceeded")
        for j in range(n):
            e = u16(buf, off + 8 + 2 * j)
            out.append(dict(block_rva=bva, type=e >> 12, offset=e & 0xFFF))
        off += bsz
    return out


def apply_relocs(image: bytearray, pe, loaded_base):
    delta = (loaded_base - pe["image_base"]) & 0xFFFFFFFFFFFFFFFF
    applied = 0
    for r in pe["relocs"]:
        t = r["type"]
        if t == 0:                       # ABSOLUTE: padding only
            continue
        if t not in (3, 10):             # HIGHLOW, DIR64
            raise PEError(f"unsupported reloc type {t}")
        off = rva_to_off(pe["sections"], r["block_rva"] + r["offset"])
        if t == 10:
            _need(image, off, 8, "DIR64 fixup")
            v = struct.unpack_from("<Q", image, off)[0]
            struct.pack_into("<Q", image, off,
                             (v + delta) & 0xFFFFFFFFFFFFFFFF)
        else:
            _need(image, off, 4, "HIGHLOW fixup")
            v = struct.unpack_from("<I", image, off)[0]
            struct.pack_into("<I", image, off, (v + delta) & 0xFFFFFFFF)
        applied += 1
    return delta, applied
