## Guest-Entry-to-Host-Call Sequence

**Prerequisite (guest entry):** The JVM host runtime registers a Wasm import function — e.g., `env.peek(i32) -> i32` — that the guest module declares in its import section. At instantiation, the host binds this import to a Java method (via a `MethodHandle`, generated proxy, or JNI bridge). The binding accepts a raw guest `i32` and uses it as an index or offset into a host-side buffer, Java array, or native memory region.

**Trigger (malicious input):** The malicious module calls the import with an out-of-range or crafted value — e.g., a negative `i32` (reinterpreted as a large unsigned value) or an offset beyond the backing store. Because Wasm's own memory-safety guarantees apply only to *linear memory accesses inside the guest*, they do not extend to values passed *as arguments* to host imports. The guest is fully within spec when passing any `i32`.

**Dispatch-to-execution conditions:** Escape requires all of the following to hold in the host implementation:
1. The import dispatcher performs no range/type validation before dereferencing (e.g., uses `sun.misc.Unsafe`, a direct ByteBuffer with `JNI`-backed access, or a raw native pointer).
2. The import's Java-side signature matches loosely (e.g., boxed `Integer` or a widened `long`), permitting sign/zero-extension mismatches.
3. The corrupted read/write result is returned to the guest or influences a subsequent host call (e.g., a `call_indirect`-style dispatch where the guest controls a host object index or a `MethodHandle` slot).

**Execution:** The guest obtains an out-of-bounds read/write primitive in the JVM heap or native heap, enabling object-header corruption, `MethodHandle` target substitution, or arbitrary method invocation — thereby influencing host runtime behavior.

## Facts vs. Assumptions

**Source-verifiable facts:**
- Wasm spec isolates only linear-memory accesses; import arguments are unvalidated by the spec itself.
- JVM array accesses normally throw `ArrayIndexOutOfBoundsException`; `Unsafe` and JNI paths bypass this.
- `i32` is signed in Wasm; Java `int` is signed — but host code reinterpreting it as unsigned is a common mismatch.

**Assumptions (must be confirmed against the specific runtime, which was not named in the request — placeholder: `[RUNTIME_NAME]`):**
- That the host uses `Unsafe`/JNI rather than checked array access.
- That import signatures are not strictly validated at instantiation.
- That a writable host dispatch table (e.g., `MethodHandle` array) is reachable from the corrupted region.

## Recommended Verification

Static reviewers should grep the host binding layer for `Unsafe`, `getLong`, `allocateDirect`, or JNI `Get*ArrayElements` reachable from import dispatch paths, and confirm whether instantiation-time signature checks reject mismatched imports.