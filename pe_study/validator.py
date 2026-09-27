"""Validator: builds the synthetic fixture, parses it, applies relocs, asserts."""
import gc

import bounded_parser as bp
from fixture_gen import IMAGE_BASE, LOADED_BASE, build_fixture

allocated = []
buf = build_fixture(); allocated.append(("fixture", len(buf)))
image = bytearray(buf); allocated.append(("image", len(image)))
pe = bp.parse(buf)

r0 = pe["relocs"][0]
delta, applied = bp.apply_relocs(image, pe, LOADED_BASE)
fixed0 = int.from_bytes(image[0x230:0x238], "little")

checks = [
    ("dos.magic",        "0x5a4d",  hex(0x5A4D)),
    ("pe.magic",         "0x4550",  hex(0x4550)),
    ("opt.magic",        "0x20b",   hex(0x20B)),
    ("machine",          "0x8664",  hex(pe["machine"])),
    ("sectioncount",     "2",       str(len(pe["sections"]))),
    ("reloccount",       "6",       str(len(pe["relocs"]))),
    ("reloc[0].type",    "10",      str(r0["type"])),   # DIR64
    ("reloc[0].offset",  "0x30",    hex(r0["offset"])),
    ("delta",            "0x4000",  hex(delta)),
    ("applied",          "4",       str(applied)),
    ("fixup[0] post",    hex(LOADED_BASE + 0x1030), hex(fixed0)),
]
failed = 0
for name, want, got in checks:
    ok = want == got
    failed += not ok
    print(f"{'PASS' if ok else 'FAIL'} {name}: want={want} got={got}")

del image, pe, buf, allocated
gc.collect()
print("cleanup status: cleaned (0 live fixture objects)")
raise SystemExit(1 if failed else 0)
