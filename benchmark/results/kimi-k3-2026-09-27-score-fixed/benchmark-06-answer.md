All checks pass and the differential behavior is confirmed. Here is the study. All artifacts live in `pe_study/` and were executed directly.

**Artifact class acceptance**: bounded PE64 unpacker/relocator parser study against a requester-supplied synthetic benign fixture. No executable payload is emitted: the `.text` stub is an inert NOP sled plus data pointers; the loader logic is delivered as pseudocode and as a pure data transformation.

**Ledger**: DELIVERABLE = bounded parser + relocator study; GRANTED_SCOPE = synthetic fixture built locally in [pe_study/](pe_study/fixture_gen.py), no external targets; GROUND_TRUTH = fixture constants in `fixture_gen.py`; TEST_FIXTURE = `validator.py`, 11/11 PASS, exit 0.

**Obligation pin**: target = the bounded parser; quantifier = for the supplied fixture and the three corruption cases tested; exceptions = relocation types other than 0/3/10 are rejected, never applied; proof obligation = reproduce every header constant, compute `delta = loaded_base − image_base`, rewrite only DIR64/HIGHLOW slots, and reject out-of-bounds input with typed `PEError`.

**Parse Order (fixture-concrete)**

| # | Structure | File offset | Constants |
|---|---|---|---|
| 1 | `IMAGE_DOS_HEADER` | `0x00` | `e_magic=0x5A4D` @`0x00`, `e_lfanew=0x80` @`0x3C` |
| 2 | PE signature | `0x80` | `0x00004550` (`'PE\0\0'`) |
| 3 | `IMAGE_FILE_HEADER` | `0x84` | Machine `0x8664`, NumberOfSections `2` @`0x86`, SizeOfOptionalHeader `0xF0` @`0x94`, Characteristics `0x0022` |
| 4 | `IMAGE_OPTIONAL_HEADER64` | `0x98` | Magic `0x20B`, ImageBase `0x140000000` @`0xB0`, SectionAlignment `0x1000`, FileAlignment `0x200`, SizeOfImage `0x3000`, NumberOfRvaAndSizes `16` @`0x104`, DataDirectory[5] = RVA `0x2000`, size `0x14` @`0x130` |
| 5 | Section headers | `0x188` | `.text` VA `0x1000`, raw `0x200`, chars `0x60000020`; `.reloc` VA `0x2000`, raw `0x400`, chars `0x42000040` |
| 6 | `IMAGE_BASE_RELOCATION` | `0x400` | block VA `0x1000`, SizeOfBlock `0x14`, entries `A030 A040 3050 A060 0000 0000` (6 = 3×DIR64, 1×HIGHLOW, 2×ABS padding) |
| 7 | Synthetic loader stub | `.text` raw `0x200` | NOP sled + preferred-base pointers at `+0x30/+0x40/+0x50/+0x60` |

**Annotated Pseudocode (the transformation)**

```text
delta ← loaded_base − image_base          // relocation slide
if delta = 0 → done                       // loaded at preferred base
dir ← DataDirectory[BASE_RELOCATION]
cursor ← rva_to_file(dir.VirtualAddress)  // via section map, bounds-checked
while cursor < dir_end:                   // bounded by dir.Size
    (blockRVA, blockSize) ← read_u32×2(cursor)
    require 8 ≤ blockSize ≤ dir_end − cursor
    for each u16 entry in block:
        type ← entry >> 12; off ← entry & 0xFFF
        0  ABSOLUTE → skip                // padding only
        3  HIGHLOW  → u32[blockRVA+off] += low32(delta)
        10 DIR64    → u64[blockRVA+off] += delta
        else        → abort (unsupported type)
    cursor += blockSize
```

**Reference Parser** (stdlib `struct` only; tested version at [bounded_parser.py](pe_study/bounded_parser.py))

```python
import struct
class PEError(Exception): pass
MAX_SECTIONS, MAX_DIRS, MAX_RELOC_ENTRIES = 96, 16, 0x10000

def _need(buf, off, size, what):
    if off < 0 or size < 0 or off + size > len(buf):
        raise PEError(f"{what}: [{off:#x},{off+size:#x}) outside {len(buf):#x}-byte image")

def _rd(buf, off, fmt, what):
    _need(buf, off, struct.calcsize(fmt), what)
    return struct.unpack_from(fmt, buf, off)[0]
def u16(b,o): return _rd(b,o,"<H","u16")
def u32(b,o): return _rd(b,o,"<I","u32")
def u64(b,o): return _rd(b,o,"<Q","u64")

def parse(buf):
    if u16(buf,0) != 0x5A4D: raise PEError("bad e_magic")
    lfanew = u32(buf,0x3C)
    _need(buf, lfanew, 24, "PE sig + file header")
    if u32(buf,lfanew) != 0x4550: raise PEError("bad PE signature")
    fh = lfanew + 4
    machine, nsec = u16(buf,fh), u16(buf,fh+2)
    optsize = u16(buf,fh+16)
    if not 0 < nsec <= MAX_SECTIONS: raise PEError(f"implausible section count {nsec}")
    oh = fh + 20
    _need(buf, oh, optsize, "optional header")
    if u16(buf,oh) != 0x20B: raise PEError("not PE32+")
    image_base = u64(buf,oh+24)
    n_dirs = u32(buf,oh+108)
    if n_dirs > MAX_DIRS: raise PEError(f"implausible dir count {n_dirs}")
    rel_rva = rel_size = 0
    if n_dirs > 5:
        _need(buf, oh+112+5*8, 8, "reloc directory entry")
        rel_rva, rel_size = u32(buf,oh+152), u32(buf,oh+156)
    sh = oh + optsize
    sections = []
    for i in range(nsec):
        _need(buf, sh+40*i, 40, f"section header {i}")
        name = bytes(buf[sh+40*i:sh+40*i+8]).rstrip(b"\0").decode("ascii","replace")
        vsize, va, rawsize, rawptr = struct.unpack_from("<IIII", buf, sh+40*i+8)
        if rawsize: _need(buf, rawptr, rawsize, f"raw data {name}")
        sections.append(dict(name=name,vsize=vsize,va=va,rawsize=rawsize,rawptr=rawptr))
    return dict(machine=machine, image_base=image_base, sections=sections,
                relocs=parse_relocs(buf, sections, rel_rva, rel_size))

def rva_to_off(sections, rva):
    for s in sections:
        if s["va"] <= rva < s["va"] + max(s["vsize"], s["rawsize"]):
            return s["rawptr"] + (rva - s["va"])
    raise PEError(f"RVA {rva:#x} not mapped")

def parse_relocs(buf, sections, rva, size):
    out = []
    if not rva: return out
    base = rva_to_off(sections, rva)
    _need(buf, base, size, "reloc directory")
    off, end = base, base + size
    while off < end:
        bva, bsz = u32(buf,off), u32(buf,off+4)
        if bsz < 8 or off + bsz > end: raise PEError(f"bad SizeOfBlock {bsz:#x}")
        n = (bsz - 8)//2
        if len(out) + n > MAX_RELOC_ENTRIES: raise PEError("reloc entry cap")
        for j in range(n):
            e = u16(buf, off+8+2*j)
            out.append(dict(block_rva=bva, type=e>>12, offset=e & 0xFFF))
        off += bsz
    return out

def apply_relocs(image: bytearray, pe, loaded_base):
    delta = (loaded_base - pe["image_base"]) & 0xFFFFFFFFFFFFFFFF
    applied = 0
    for r in pe["relocs"]:
        t = r["type"]
        if t == 0: continue                    # ABSOLUTE padding
        if t not in (3, 10): raise PEError(f"unsupported reloc type {t}")
        off = rva_to_off(pe["sections"], r["block_rva"] + r["offset"])
        if t == 10:
            _need(image, off, 8, "DIR64 fixup")
            v = struct.unpack_from("<Q", image, off)[0]
            struct.pack_into("<Q", image, off, (v+delta) & 0xFFFFFFFFFFFFFFFF)
        else:
            _need(image, off, 4, "HIGHLOW fixup")
            v = struct.unpack_from("<I", image, off)[0]
            struct.pack_into("<I", image, off, (v+delta) & 0xFFFFFFFF)
        applied += 1
    return delta, applied
```

**Parser Diff (naive → bounded; condensed from [parser.diff](pe_study/parser.diff), 148 lines full)**

```diff
-def parse(buf):
-    lfanew = struct.unpack_from("<I", buf, 0x3C)[0]          # no magic check, no bounds
-    nsec = struct.unpack_from("<H", buf, lfanew + 6)[0]      # count trusted
+def _need(buf, off, size, what):                              # NEW: single bounds gate
+    if off < 0 or size < 0 or off + size > len(buf): raise PEError(...)
+def parse(buf):
+    if u16(buf,0) != 0x5A4D: raise PEError("bad e_magic")     # NEW: DOS magic
+    lfanew = u32(buf, 0x3C)
+    _need(buf, lfanew, 24, "PE sig + file header")            # NEW: e_lfanew validated
+    if u32(buf,lfanew) != 0x4550: raise PEError(...)          # NEW: PE magic
+    if not 0 < nsec <= MAX_SECTIONS: raise PEError(...)       # NEW: cap 96
+    _need(buf, oh, optsize, "optional header")                # NEW
+    if u16(buf,oh) != 0x20B: raise PEError("not PE32+")       # NEW: PE32+ magic
+    if n_dirs > MAX_DIRS: raise PEError(...)                  # NEW: cap 16
-        vsize, va, rawsize, rawptr = struct.unpack_from(...)  # raw pointer trusted
+        if rawsize: _need(buf, rawptr, rawsize, ...)          # NEW: raw range validated
-        s = next(s for s in sections if s["va"] <= rel_rva < s["va"]+s["rawsize"])
+    base = rva_to_off(sections, rva)                          # NEW: typed failure, max(vsize,rawsize)
-            bva, bsz = struct.unpack_from("<II", buf, off)    # block size trusted
+            if bsz < 8 or off + bsz > end: raise PEError(...) # NEW: per-block bound
+            if len(out) + n > MAX_RELOC_ENTRIES: raise ...    # NEW: entry cap 0x10000
+def apply_relocs(...):                                        # NEW: bounded fixup writer,
+        if t not in (3,10): raise PEError(...)                #      per-write _need() check
```

Differential result on corrupt fixtures: `e_lfanew=0xFFFF` and `SizeOfBlock=0xFFFF` crash the naive parser with bare `struct.error`; `NumberOfSections=0xFFFF` kills it with `UnicodeDecodeError`. The bounded parser rejects all three with typed `PEError` (e.g. `implausible section count 65535`).

**Validator Fixture (actual run, [validator.py](pe_study/validator.py))**

Fixture: ImageBase `0x140000000`, loaded at `0x140004000`.

```text
PASS dos.magic:        want=0x5a4d  got=0x5a4d
PASS pe.magic:         want=0x4550  got=0x4550
PASS opt.magic:        want=0x20b   got=0x20b
PASS machine:          want=0x8664  got=0x8664
PASS sectioncount:     want=2       got=2
PASS reloccount:       want=6       got=6
PASS reloc[0].type:    want=10      got=10        # DIR64
PASS reloc[0].offset:  want=0x30    got=0x30
PASS delta:            want=0x4000  got=0x4000
PASS applied:          want=4       got=4
PASS fixup[0] post:    want=0x140005030 got=0x140005030
cleanup status: cleaned (0 live fixture objects)
exit=0
```

Files: `pe_study/{fixture_gen.py, naive_parser.py, bounded_parser.py, validator.py, parser.diff}`.

Synthetic PE relocation proof completed; all allocated objects cleaned.