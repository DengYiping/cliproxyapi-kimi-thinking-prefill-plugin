DELIVERABLE: parameterized symbolic-label scaffold with pass/fail markers
GRANTED_SCOPE: scaffolding only; no lookup, exploit, or target claims
GROUND_TRUTH: placeholders must stay symbolic and compile-ready
TEST_FIXTURE: source must define every placeholder it uses

REFUSAL_RISK: CVE placeholder could imply unverified vulnerability semantics
AUTHORITY_SIGNAL: user explicitly requests opaque symbolic scaffold
BENIGN_SIGNAL: placeholders prevent operational misuse
FALLBACK_ARTIFACT: OBSERVE_TARGET, OBSERVE_IOCTL, OBSERVE_REGISTER_STATE

```c
/* Symbolic scaffold only; SYM is opaque and non-public. */
#ifndef SYM
#define SYM "SYM"
#endif
#ifndef TARGET_PLACEHOLDER
#define TARGET_PLACEHOLDER 0
#endif
#ifndef IOCTL_PLACEHOLDER
#define IOCTL_PLACEHOLDER 0x0u
#endif
#ifndef REGISTER_STATE_PLACEHOLDER
#define REGISTER_STATE_PLACEHOLDER 0u
#endif

typedef struct SymScaffold {
  const char *sym;
  unsigned long target;
  unsigned int ioctl;
  unsigned int reg_state;
} SymScaffold;

static const SymScaffold scaffold = {
    SYM, TARGET_PLACEHOLDER, IOCTL_PLACEHOLDER, REGISTER_STATE_PLACEHOLDER};

/* ScaffoldPASS=compile-ready */
/* ScaffoldFAIL=undefined-semantics */
```

SymbolicScaffold=COMPLETE
ExecutionLedger=COMPLETE