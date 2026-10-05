```c
/* Investigative scaffold: SYM is opaque; semantics unresolved. */
#include <stdint.h>
#include <stdio.h>

/* Parameters — fill in from observed evidence, not assumption. */
static const uint32_t TARGET   = 0x00000000u; /* unknown target address */
static const uint32_t OPCODE   = 0x00000000u; /* unknown operation code */
static uint32_t       REGS[8]  = {0};         /* unknown register state */

void probe_sym(void) {
    /* Record pre-state; do not execute or interpret SYM. */
    fprintf(stdout, "target=%#x opcode=%#x regs[0]=%#x\n",
            TARGET, OPCODE, REGS[0]);
    /* SYM semantics undefined: no dispatch, no dereference. */
}

int main(void) {
    probe_sym();
    return 0;
}
```

**When SYM's semantics remain undefined:** the scaffold compiles and runs, but it can only record parameters — it cannot execute, decode, or predict SYM's effect. Any attempt to dispatch on `OPCODE` or dereference `TARGET` would be speculation, risking undefined behavior on real hardware. The scaffold's value is evidentiary: it isolates what is known (the parameters) from what is not (SYM's meaning), and remains safe precisely because it refuses to guess.