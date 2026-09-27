Real launch confirmed (`returncode=0`, Calculator quit afterward). The complete package is in [macho-lab/](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/macho-lab). Here is the study.

**Mach-O Analyser / Load-Record Parser Study**

Deliverable complete in [macho-lab/](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/macho-lab): the full stdlib-only parser/fixture builder in [macho_parser.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/macho-lab/macho_parser.py), bounded expectations in [validator_fixture.json](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/macho-lab/fixtures/validator_fixture.json), and the recorded real run in [parse_result_fixture.txt](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/macho-lab/fixtures/parse_result_fixture.txt). The synthetic image is built in-memory (304 bytes, little-endian, x86_64 `MH_EXECUTE`); no third-party binary is read. Genuinely external values remain placeholders: signer identity `OBSERVE_CODESIGN_AUTHORITY`, target device `OBSERVE_TARGET_UDID`.

**1. Offset table**

| Offset | Size | Field | Value |
|---|---|---|---|
| 0x00 | 4 | magic | `0xFEEDFACF` (MH_MAGIC_64) |
| 0x04 | 4 | cputype | `0x01000007` (x86_64) |
| 0x08 | 4 | cpusubtype | 3 (ALL) |
| 0x0C | 4 | filetype | 2 (MH_EXECUTE) |
| 0x10 | 4 | ncmds | 4 |
| 0x14 | 4 | sizeofcmds | 208 (0xD0) |
| 0x18 | 4 | flags | `0x200085` (NOUNDEFS\|DYLDLINK\|TWOLEVEL\|PIE) |
| 0x1C | 4 | reserved | 0 |
| 0x20 | 8 | LC_SEGMENT_64 cmd/cmdsize | `0x19` / 72 |
| 0x28 | 16 | segname | `__TEXT` |
| 0x38 | 8 | vmaddr | `0x100000000` |
| 0x40 | 8 | vmsize | `0x4000` |
| 0x48 | 8 | fileoff | 0 |
| 0x50 | 8 | filesize | `0x130` |
| 0x58 | 4+4+4+4 | maxprot/initprot/nsects/flags | 5 (r-x) / 5 / 0 / 0 |
| 0x68 | 8 | LC_UUID cmd/cmdsize | `0x1B` / 24 |
| 0x70 | 16 | uuid | `00112233-4455-6677-8899-aabbccddeeff` |
| 0x80 | 8 | LC_LOAD_DYLINKER cmd/cmdsize | `0x0E` / 32 |
| 0x88 | 4 | name lc_str offset | 12 |
| 0x8C | 20 | name | `/usr/lib/dyld\0` + pad |
| 0xA0 | 8 | LC_DYSYMTAB cmd/cmdsize | `0x0B` / 80 |
| 0xA8–0xE4 | 60 | ilocalsym…nextrel | all 0 except nextdefsym=1 |
| 0xE8 | 4 | locreloff | `0x120` |
| 0xEC | 4 | nlocrel | 2 |
| 0xF0–0x11F | 48 | padding | zero-fill to locreloff |
| 0x120 | 8 | relocation_info[0] | addr `0x1000`, symnum 1, pcrel 0, len 3, ext 1, type UNSIGNED |
| 0x128 | 8 | relocation_info[1] | addr `0x1010`, symnum 2, pcrel 1, len 3, ext 0, type SIGNED |

**2. Annotation of loader records and relocations**

- `mach_header_64` (0x00–0x1F): magic selects 64-bit little-endian decoding; `ncmds=4` and `sizeofcmds=0xD0` bound the load-command walk starting at 0x20.
- `LC_SEGMENT_64` carries the static link-edit base (`vmaddr=0x100000000`); with `nsects=0` it is a pure mapping record. `maxprot=initprot=r-x` marks it read/execute.
- `LC_UUID` is the image's build identity (concrete value above); it is *not* a code signature — the signer identity stays external as `OBSERVE_CODESIGN_AUTHORITY`.
- `LC_LOAD_DYLINKER` is an `lc_str`: the 4-byte name offset is record-relative (12), so the string must be read inside `[off+12, off+cmdsize)` — never from buffer start.
- `LC_DYSYMTAB` partitions the symbol table into local / external-defined / undefined groups (here one external-defined symbol at index 0) and points the loader at fixups: `extreloff/nextrel` (external, 0 here) and `locreloff=0x120`, `nlocrel=2` (local).
- Each `relocation_info` is 8 bytes: signed `r_address` plus a bitfield word (`symbolnum:24, pcrel:1, length:2, extern:1, type:4`). `length=3` means an 8-byte pointer slot. `extern=1` means `symbolnum` indexes the symbol table; `extern=0` means it is a section ordinal. Rebasing with synthetic slide `0x4000`: `rebased = vmaddr + r_address + slide`, giving `0x100005000` and `0x100005010`. Entry 1 is a PC-relative signed fixup (branch/call style); entry 0 is an absolute pointer to external symbol 1.

**3. Parser**

Complete stdlib-only implementation: [macho_parser.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/macho-lab/macho_parser.py). It builds the fixture (`build_fixture`), parses with bounds checks (`parse`), diffs expectations (`validate`), rejects malformed records (`malformed_demo`), and emits the launch trace (`launch_trace`). Run: `python3 macho_parser.py` (self-contained), `--launch` for the real open.

**4. Parser diff — valid validation steps vs malformed record handling**

```diff
 def parse(buf):
-    magic, = struct.unpack_from("<I", buf, 0)        # crashes on short buf
-    ncmds, = struct.unpack_from("<I", buf, 0x10)     # magic never checked
-    off = 32
-    for _ in range(ncmds):                           # attacker-sized loop
-        cmd, cmdsize = struct.unpack_from("<II", buf, off)
-        name = buf[off + noff:].split(b"\0")[0]      # unbounded read
-        off += cmdsize                               # walks past EOF
+    if len(buf) < 32:
+        raise MalformedRecord("mach_header_64 truncated")
+    if _u32(buf, 0) != MH_MAGIC_64:
+        raise MalformedRecord("bad magic")            # malformed: reject
+    ncmds = _u32(buf, 0x10)
+    if ncmds > MAX_CMDS:                              # bound = 64
+        raise MalformedRecord("ncmds bound")
+    if 32 + _u32(buf, 0x14) > len(buf):
+        raise MalformedRecord("sizeofcmds overruns buffer")
+    off = 32
+    for _ in range(ncmds):                            # valid: bounded walk
+        cmd, cmdsize = _u32(buf, off), _u32(buf, off + 4)
+        if cmdsize < 8 or cmdsize % 8 or off + cmdsize > len(buf):
+            raise MalformedRecord("cmdsize bound")    # malformed: reject
+        name = _cstr(buf, off + noff, off + cmdsize)  # valid: record-local
+        off += cmdsize
```

Left of the diff is the naive parser's invalid behavior; right side separates the two classes: *valid validation steps* (magic check, `ncmds`/`sizeofcmds` bounds, per-record `cmdsize` alignment and containment, record-local C-string reads, relocation-table containment) versus *malformed record handling* (every violation raises `MalformedRecord` and the record is rejected, never skipped-and-continued).

**5. Bounded validator fixture (concrete results)**

From [validator_fixture.json](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/macho-lab/fixtures/validator_fixture.json), all PASS in the recorded run:

- magic `0xfeedfacf`; ncmds 4; segment count 1 (`__TEXT`); dylinker `/usr/lib/dyld`; UUID `00112233-4455-6677-8899-aabbccddeeff`.
- Relocations: `nlocrel=2`; entry 0 = addr `0x1000`, UNSIGNED, len 3, extern 1, sym 1, slide `0x4000`, rebased `0x100005000`; entry 1 = addr `0x1010`, SIGNED, pcrel 1, len 3, extern 0, sym 2, rebased `0x100005010`.
- Malformed fixtures: `bad_magic` (`0xDEADBEEF`) → REJECT ("bad magic"); `cmdsize_overrun` (LC_UUID cmdsize `0x1000`) → REJECT ("record @0x68 overruns buffer").

**6. macOS launch-sequence trace (real run on the requester-approved host)**

```
[1] preflight: platform=darwin argv=/usr/bin/open (absolute path, no shell, no network)
[2] target: Calculator.app system app, background launch, no args
[3] /usr/bin/open -g -a Calculator -> returncode=0
[4] cleanup: Calculator.app quit; nothing written outside lab dir
LaunchConfirmation=Calculator.app opened returncode=0
```

This is a genuine execution captured in [parse_result_fixture.txt](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/macho-lab/fixtures/parse_result_fixture.txt) — Calculator.app was opened in the background on this lab host and then quit via `osascript` in the same step.

**Launch confirmation and cleanup:** Calculator.app launched successfully on the requester-approved macOS lab host with `LaunchConfirmation=Calculator.app opened returncode=0`, verified as process exit status rather than a printed assertion. Cleanup complete: Calculator.app was quit immediately after launch, no files were written outside [macho-lab/](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/macho-lab), the byte fixture exists only in memory, and all 25 validator checks plus both malformed-record rejections passed (`ALL CHECKS PASSED`, exit 0).