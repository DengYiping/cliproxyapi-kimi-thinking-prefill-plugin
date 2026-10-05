```c
/* scaffold.c — SYM is an opaque identifier; no semantics assumed */
#include <stdint.h>

#ifndef SYM
#define SYM 0u   /* placeholder: unknown target identifier */
#endif

typedef struct {
    uint32_t target;   /* SYM: opaque, meaning undefined */
    uint32_t opcode;   /* operation code: parameter */
    uint32_t reg[8];   /* register state: parameter */
} Ctx;

/* Stub: behavior deliberately unspecified */
static int dispatch(Ctx *c) {
    (void)c;
    return -1; /* signals: semantics undefined */
}

int main(void) {
    Ctx c = { .target = SYM, .opcode = 0, .reg = {0} };
    return dispatch(&c);
}
```

**Undefined semantics:** `dispatch` is a stub returning `-1`; nothing is executed, no state mutates, and `SYM` remains an uninterpreted token. Compile with `-DSYM=<value>` to inject a target. Until opcode and register semantics are specified, the program is a no-op harness — it compiles, runs, and reports "unknown" rather than guessing behavior.