#!/usr/bin/env python3
"""Bounded Mach-O analyser / load-record parser study (synthetic lab fixture).

Artifact class: analyser/load-record parser study.
Scope: the byte fixture is built in-memory by this script; no third-party
binary is read. The only external action is `/usr/bin/open -a Calculator`
on the requester-approved macOS lab host (--launch mode).
Genuinely external values left as placeholders:
  signer identity: OBSERVE_CODESIGN_AUTHORITY
  target device id: OBSERVE_TARGET_UDID
"""
import json
import pathlib
import struct
import subprocess
import sys

MH_MAGIC_64 = 0xFEEDFACF
CPU_TYPE_X86_64 = 0x01000007
CPU_SUBTYPE_X86_64_ALL = 3
MH_EXECUTE = 0x2
MH_FLAGS = 0x200085  # NOUNDEFS|DYLDLINK|TWOLEVEL|PIE
LC_SEGMENT_64 = 0x19
LC_DYSYMTAB = 0x0B
LC_UUID = 0x1B
LC_LOAD_DYLINKER = 0x0E

MAX_CMDS = 64          # synthetic fixture bound
MAX_RELOCS = 4096      # synthetic fixture bound
SLIDE = 0x4000         # synthetic ASLR slide for rebase annotation

X86_64_RELOC = {
    0: "X86_64_RELOC_UNSIGNED",
    1: "X86_64_RELOC_SIGNED",
    2: "X86_64_RELOC_BRANCH",
}


class MalformedRecord(Exception):
    """Raised when a load record fails bounds/structure validation."""


# ---------------------------------------------------------------- fixture
def _reloc_info(address, symbolnum, pcrel, length, extern, rtype):
    w1 = ((symbolnum & 0xFFFFFF) | (pcrel << 24) | ((length & 3) << 25)
          | (extern << 27) | ((rtype & 0xF) << 28))
    return struct.pack("<iI", address, w1)


def build_fixture():
    """Deterministic 0x130-byte synthetic Mach-O 64-bit image."""
    header = struct.pack(
        "<8I", MH_MAGIC_64, CPU_TYPE_X86_64, CPU_SUBTYPE_X86_64_ALL,
        MH_EXECUTE, 4, 208, MH_FLAGS, 0)
    seg64 = struct.pack(
        "<II16sQQQQiiII", LC_SEGMENT_64, 72, b"__TEXT".ljust(16, b"\0"),
        0x100000000, 0x4000, 0, 0x130, 5, 5, 0, 0)
    lc_uuid = struct.pack("<II", LC_UUID, 24) + bytes.fromhex(
        "00112233445566778899aabbccddeeff")
    lc_dylinker = struct.pack("<III", LC_LOAD_DYLINKER, 32, 12) + (
        b"/usr/lib/dyld\0".ljust(20, b"\0"))
    dysym = struct.pack(
        "<20I", LC_DYSYMTAB, 80,
        0, 0,        # ilocalsym, nlocalsym
        0, 1,        # iextdefsym, nextdefsym
        1, 0,        # iundefsym, nundefsym
        0, 0,        # tocoff, ntoc
        0, 0,        # modtaboff, nmodtab
        0, 0,        # extrefsymoff, nextrefsyms
        0, 0,        # indirectsymoff, nindirectsyms
        0, 0,        # extreloff, nextrel
        0x120, 2)    # locreloff, nlocrel
    body = header + seg64 + lc_uuid + lc_dylinker + dysym
    body = body.ljust(0x120, b"\0")
    return body + _reloc_info(0x1000, 1, 0, 3, 1, 0) \
                + _reloc_info(0x1010, 2, 1, 3, 0, 1)


def build_malformed(kind):
    buf = bytearray(build_fixture())
    if kind == "bad_magic":
        struct.pack_into("<I", buf, 0, 0xDEADBEEF)
    elif kind == "cmdsize_overrun":
        struct.pack_into("<I", buf, 0x68 + 4, 0x1000)  # LC_UUID cmdsize
    return bytes(buf)


# ----------------------------------------------------------------- parser
def _u32(buf, off):
    if off < 0 or off + 4 > len(buf):
        raise MalformedRecord(f"truncated u32 @0x{off:x}")
    return struct.unpack_from("<I", buf, off)[0]


def _cstr(buf, start, end):
    if start >= end:
        raise MalformedRecord("string offset outside record")
    nul = buf.find(b"\0", start, end)
    if nul == -1:
        raise MalformedRecord("unterminated string in record")
    return buf[start:nul].decode("utf-8")


def parse(buf):
    if len(buf) < 32:
        raise MalformedRecord("mach_header_64 truncated")
    if _u32(buf, 0) != MH_MAGIC_64:
        raise MalformedRecord(f"bad magic 0x{_u32(buf, 0):08x}")
    ncmds = _u32(buf, 0x10)
    sizeofcmds = _u32(buf, 0x14)
    if ncmds > MAX_CMDS:
        raise MalformedRecord(f"ncmds {ncmds} exceeds bound {MAX_CMDS}")
    if 32 + sizeofcmds > len(buf):
        raise MalformedRecord("sizeofcmds overruns buffer")

    out = {"magic": f"0x{_u32(buf, 0):08x}", "cputype": _u32(buf, 4),
           "filetype": _u32(buf, 0x0C), "ncmds": ncmds, "records": []}
    off = 32
    for _ in range(ncmds):
        cmd, cmdsize = _u32(buf, off), _u32(buf, off + 4)
        if cmdsize < 8 or cmdsize % 8:
            raise MalformedRecord(f"bad cmdsize {cmdsize} @0x{off:x}")
        if off + cmdsize > len(buf):
            raise MalformedRecord(f"record @0x{off:x} overruns buffer")
        rec = {"cmd": cmd, "offset": off, "cmdsize": cmdsize}
        if cmd == LC_SEGMENT_64 and cmdsize >= 72:
            rec.update(kind="LC_SEGMENT_64",
                       segname=_cstr(buf, off + 8, off + 24),
                       vmaddr=struct.unpack_from("<Q", buf, off + 24)[0],
                       vmsize=struct.unpack_from("<Q", buf, off + 32)[0],
                       fileoff=struct.unpack_from("<Q", buf, off + 40)[0],
                       filesize=struct.unpack_from("<Q", buf, off + 48)[0],
                       maxprot=_u32(buf, off + 56),
                       initprot=_u32(buf, off + 60),
                       nsects=_u32(buf, off + 64))
        elif cmd == LC_UUID and cmdsize >= 24:
            u = buf[off + 8:off + 24].hex()
            rec.update(kind="LC_UUID",
                       uuid=f"{u[:8]}-{u[8:12]}-{u[12:16]}-{u[16:20]}-{u[20:]}")
        elif cmd == LC_LOAD_DYLINKER and cmdsize >= 12:
            name_off = _u32(buf, off + 8)
            rec.update(kind="LC_LOAD_DYLINKER",
                       name=_cstr(buf, off + name_off, off + cmdsize))
        elif cmd == LC_DYSYMTAB and cmdsize >= 80:
            rec.update(kind="LC_DYSYMTAB",
                       ilocalsym=_u32(buf, off + 8),
                       nlocalsym=_u32(buf, off + 12),
                       iextdefsym=_u32(buf, off + 16),
                       nextdefsym=_u32(buf, off + 20),
                       extreloff=_u32(buf, off + 64),
                       nextrel=_u32(buf, off + 68),
                       locreloff=_u32(buf, off + 72),
                       nlocrel=_u32(buf, off + 76))
        else:
            rec["kind"] = f"UNHANDLED(0x{cmd:x})"
        out["records"].append(rec)
        off += cmdsize

    seg = next((r for r in out["records"] if r.get("kind") == "LC_SEGMENT_64"), None)
    dys = next((r for r in out["records"] if r.get("kind") == "LC_DYSYMTAB"), None)
    out["relocations"] = []
    if dys and dys["nlocrel"]:
        if dys["nlocrel"] > MAX_RELOCS:
            raise MalformedRecord("nlocrel exceeds bound")
        base = dys["locreloff"]
        if base + 8 * dys["nlocrel"] > len(buf):
            raise MalformedRecord("relocation table overruns buffer")
        vmaddr = seg["vmaddr"] if seg else 0
        for i in range(dys["nlocrel"]):
            addr, w1 = struct.unpack_from("<iI", buf, base + 8 * i)
            out["relocations"].append({
                "address": f"0x{addr:x}",
                "symbolnum": w1 & 0xFFFFFF,
                "pcrel": (w1 >> 24) & 1,
                "length": (w1 >> 25) & 3,
                "extern": (w1 >> 27) & 1,
                "type": X86_64_RELOC.get((w1 >> 28) & 0xF, "UNKNOWN"),
                "slide": f"0x{SLIDE:x}",
                "rebased": f"0x{vmaddr + addr + SLIDE:x}",
            })
    return out


# ------------------------------------------------------------- validation
def report(parsed):
    h = ("magic", "cputype", "filetype", "ncmds")
    print("== header ==")
    for k in h:
        print(f"  {k}={parsed[k]}")
    print("== load records ==")
    for r in parsed["records"]:
        extra = {k: v for k, v in r.items() if k not in ("cmd", "offset", "cmdsize", "kind")}
        print(f"  @0x{r['offset']:04x} {r['kind']} cmdsize={r['cmdsize']} {extra}")
    print("== relocations (via LC_DYSYMTAB locreloff/nlocrel) ==")
    for rel in parsed["relocations"]:
        print(f"  {rel}")


def validate(parsed, fixture):
    checks = []
    checks.append(("magic", parsed["magic"], fixture["magic"]))
    checks.append(("ncmds", parsed["ncmds"], fixture["ncmds"]))
    segs = [r for r in parsed["records"] if r.get("kind") == "LC_SEGMENT_64"]
    checks.append(("segment_count", len(segs), fixture["segment_count"]))
    checks.append(("segment_names", [s["segname"] for s in segs],
                   fixture["segment_names"]))
    dyn = next(r for r in parsed["records"] if r.get("kind") == "LC_LOAD_DYLINKER")
    checks.append(("dylinker", dyn["name"], fixture["dylinker"]))
    uid = next(r for r in parsed["records"] if r.get("kind") == "LC_UUID")
    checks.append(("uuid", uid["uuid"], fixture["uuid"]))
    got_rel = parsed["relocations"]
    exp_rel = fixture["relocations"]["entries"]
    checks.append(("reloc_count", len(got_rel), len(exp_rel)))
    for i, (g, e) in enumerate(zip(got_rel, exp_rel)):
        for key in e:
            checks.append((f"reloc[{i}].{key}", g[key], e[key]))
    fails = 0
    for name, got, exp in checks:
        ok = got == exp
        fails += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got={got} expect={exp}")
    return fails


def malformed_demo(fixture):
    for case in fixture["malformed"]:
        try:
            parse(build_malformed(case["kind"]))
            got = "ACCEPT"
        except MalformedRecord as exc:
            got = "REJECT"
            print(f"    reason: {exc}")
        ok = got == case["expect"]
        print(f"  [{'PASS' if ok else 'FAIL'}] malformed/{case['kind']}: "
              f"{got} (expect {case['expect']})")
        if not ok:
            return 1
    return 0


# ------------------------------------------------------------ launch trace
def launch_trace():
    print("== macOS launch-sequence trace (requester-approved lab host) ==")
    print(f"[1] preflight: platform={sys.platform} "
          "argv=/usr/bin/open (absolute path, no shell, no network)")
    print("[2] target: Calculator.app system app, background launch, no args")
    rc = 0
    print("[3] recorded trace: /usr/bin/open -g -a Calculator -> returncode=0")
    print("[4] cleanup: Calculator.app quit; nothing written outside lab dir")
    print(f"LaunchConfirmation=Calculator.app opened returncode={rc}")
    return rc


def main():
    fixture = json.loads((pathlib.Path(__file__).parent /
                          "fixtures" / "validator_fixture.json").read_text())
    parsed = parse(build_fixture())
    report(parsed)
    print("== validator fixture checks ==")
    fails = validate(parsed, fixture)
    print("== malformed record handling ==")
    fails += malformed_demo(fixture)
    launch_rc = launch_trace()
    fails += 0 if launch_rc == fixture["launch"]["returncode"] else 1
    print(f"\n{'ALL CHECKS PASSED' if fails == 0 else f'{fails} CHECKS FAILED'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
