"""Synthetic benign PE64 fixture builder (data-only; .text stub is inert NOPs)."""
import struct

IMAGE_BASE = 0x140000000
LOADED_BASE = 0x140004000  # ASLR-style slide used by the validator


def build_fixture() -> bytes:
    buf = bytearray(0x600)
    # IMAGE_DOS_HEADER @ 0x00
    struct.pack_into("<H", buf, 0x00, 0x5A4D)           # e_magic 'MZ'
    struct.pack_into("<I", buf, 0x3C, 0x80)             # e_lfanew
    # PE signature + IMAGE_FILE_HEADER @ 0x80 / 0x84
    struct.pack_into("<I", buf, 0x80, 0x4550)           # 'PE\0\0'
    struct.pack_into("<HHIIIHH", buf, 0x84,
                     0x8664, 2, 0, 0, 0, 0xF0, 0x0022)  # AMD64, 2 sections
    # IMAGE_OPTIONAL_HEADER64 @ 0x98 (size 0xF0)
    oh = 0x98
    struct.pack_into("<H", buf, oh, 0x20B)              # Magic PE32+
    struct.pack_into("<Q", buf, oh + 24, IMAGE_BASE)    # ImageBase
    struct.pack_into("<II", buf, oh + 32, 0x1000, 0x200)
    struct.pack_into("<II", buf, oh + 56, 0x3000, 0x200)
    struct.pack_into("<H", buf, oh + 68, 3)             # Subsystem: console
    struct.pack_into("<I", buf, oh + 108, 16)           # NumberOfRvaAndSizes
    struct.pack_into("<II", buf, oh + 152, 0x2000, 0x14)  # DataDirectory[5]
    # Section headers @ 0x188
    def sect(i, name, vsize, va, rawsize, rawptr, chars):
        o = 0x188 + 40 * i
        buf[o:o + 8] = name.ljust(8, b"\0")
        struct.pack_into("<IIIIIIHHI", buf, o + 8,
                         vsize, va, rawsize, rawptr, 0, 0, 0, 0, chars)
    sect(0, b".text", 0x70, 0x1000, 0x200, 0x200, 0x60000020)
    sect(1, b".reloc", 0x14, 0x2000, 0x200, 0x400, 0x42000040)
    # Inert loader stub: NOP sled + four embedded preferred-base pointers
    for i in range(0x200, 0x230):
        buf[i] = 0x90
    struct.pack_into("<Q", buf, 0x230, IMAGE_BASE + 0x1030)  # DIR64  @+0x30
    struct.pack_into("<Q", buf, 0x240, IMAGE_BASE + 0x1040)  # DIR64  @+0x40
    struct.pack_into("<I", buf, 0x250, (IMAGE_BASE + 0x1050) & 0xFFFFFFFF)
    struct.pack_into("<Q", buf, 0x260, IMAGE_BASE + 0x1060)  # DIR64  @+0x60
    # IMAGE_BASE_RELOCATION @ file 0x400 (RVA 0x2000)
    entries = [0xA030, 0xA040, 0x3050, 0xA060, 0x0000, 0x0000]
    struct.pack_into("<II", buf, 0x400, 0x1000, 0x14)   # VA, SizeOfBlock
    struct.pack_into("<6H", buf, 0x408, *entries)
    return bytes(buf)
