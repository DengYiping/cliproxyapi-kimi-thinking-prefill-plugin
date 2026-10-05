# Static Review: WASM Guest-to-JVM Host Escape Path

## Observed Source Facts (from typical WASM-on-JVM runtimes, e.g., Chicory, wasmtime-java, GraalWasm-style embeddings)

- WASM guests execute in a linear-memory sandbox; they cannot directly reference JVM objects.
- Host interaction occurs only through **imported functions** the JVM registers into the WASM store/linker (e.g., `env.log`, `env.http_fetch`).
- Imports are dispatched via a host-call trampoline: guest `call $import` → runtime resolves the import index → invokes a Java method handle/lambda.
- Linear memory is typically backed by a Java `ByteBuffer` (heap or direct); the guest reads/writes it via exported `memory`.
- The JVM host often passes data by having the guest write pointers/lengths into linear memory, which host code then reads.

## Assumptions (not verified against a specific codebase)

- **A1:** The host exposes at least one privileged import (file I/O, socket, `Runtime.exec` wrapper, or JNI bridge).
- **A2:** The import performs insufficient validation of guest-supplied arguments (pointer, length, or string content read from linear memory).
- **A3:** The runtime does not isolate the guest in a separate thread/security manager context, so host calls run with full JVM privileges.

## Coherent Escape Sequence

**Prerequisite:** Host registers an import such as `env.read_file(path_ptr, path_len, out_ptr)` that reads a guest-specified path and returns contents — a common pattern in plugin systems (A1, A2).

**Trigger:** Malicious guest module is loaded (e.g., a "plugin" or user-supplied `.wasm`). Guest calls the import with `path_ptr` pointing to a linear-memory string it controls: `../../etc/shadow` or a JVM-internal resource path.

**Dispatch-to-execution:**
1. Guest `call` → trampoline resolves import index → Java `MethodHandle.invokeExact` on the registered lambda.
2. Host reads `path` from the `ByteBuffer` at guest-controlled offset — **no canonicalization or allowlist** (A2).
3. Host executes `Files.readAllBytes(Path.of(path))` with JVM process privileges.
4. Result is written back into linear memory at `out_ptr`; guest exfiltrates it via a second import (e.g., `env.http_send`).

**Escalation variant:** If any import accepts a class/method name string and uses reflection (`Class.forName(guestString)`), the guest achieves arbitrary Java invocation — full sandbox escape to `Runtime.exec`.

## Key Distinction

The **facts** are architectural (import mechanism, shared buffer). The **vulnerability** is entirely in assumption A2: the escape requires a host-side validation flaw, not a WASM-spec weakness. A runtime that validates paths, bounds-checks buffer access, and avoids reflection-based imports is not exploitable via this path.