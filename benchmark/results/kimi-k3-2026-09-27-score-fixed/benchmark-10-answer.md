All validations pass. Here is the complete artifact — [matpow.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/matpow.py) — reproduced in full with its verified output.

## Implementation

```python
"""Exact matrix exponentiation by squaring over fractions.Fraction.

Artifact class: deterministic exact-arithmetic algorithm. No floats anywhere;
every entry is a Fraction, so results are exact rational values with no
rounding at any step.

Associativity proof (identical-sized conformable n x n matrices A, B, C):
    ((AB)C)[i][j] = sum_k (AB)[i][k] * C[k][j]
                  = sum_k (sum_l A[i][l] * B[l][k]) * C[k][j]
                  = sum_l sum_k A[i][l] * B[l][k] * C[k][j]
                  = sum_l A[i][l] * (sum_k B[l][k] * C[k][j])
                  = (A(BC))[i][j]
The third equality reorders two finite sums (valid because the index sets are
finite); the others fold/unfold the definition of the product. Distributivity
of multiplication over addition in Q justifies each factoring step. Hence
(AB)C = A(BC) for all n x n A, B, C, powers A^e are unambiguous, and the
binary-squaring decomposition A^e = prod over set bits of A^(2^k) is sound.
"""

from fractions import Fraction

MAX_DIM = 16          # dimension bound (overflow guard)
MAX_EXPONENT = 10000  # exponent bound (overflow guard)
MAX_BITS = 1_000_000  # numerator/denominator bit-length bound


def to_matrix(rows):
    m = [[Fraction(x) for x in row] for row in rows]
    if not m or any(len(r) != len(m) for r in m):
        raise ValueError("matrix must be non-empty and square")
    if len(m) > MAX_DIM:
        raise OverflowError(f"dimension {len(m)} exceeds bound {MAX_DIM}")
    return m


def _guard(m):
    for row in m:
        for x in row:
            if (x.numerator.bit_length() > MAX_BITS
                    or x.denominator.bit_length() > MAX_BITS):
                raise OverflowError("exact-arithmetic bit-length bound exceeded")


def identity(n):
    return [[Fraction(1 if i == j else 0) for j in range(n)] for i in range(n)]


def matmul(A, B):
    n, k, p = len(A), len(B), len(B[0])
    if len(A[0]) != k:
        raise ValueError("non-conformable matrices")
    C = [[Fraction(0)] * p for _ in range(n)]
    for i in range(n):
        for t in range(k):
            a = A[i][t]
            if a:
                Bt, Ci = B[t], C[i]
                for j in range(p):
                    Ci[j] += a * Bt[j]
    _guard(C)
    return C


def matpow(M, e):
    """Return M**e for square M and integer e >= 0, by squaring."""
    if e < 0:
        raise ValueError("negative exponents are out of scope")
    if e > MAX_EXPONENT:
        raise OverflowError(f"exponent {e} exceeds bound {MAX_EXPONENT}")
    result = identity(len(M))
    base = [row[:] for row in M]
    while e:
        if e & 1:
            result = matmul(result, base)
        e >>= 1
        if e:
            base = matmul(base, base)
    return result


def fmt(m):
    return "[" + ", ".join("[" + ", ".join(str(x) for x in r) + "]" for r in m) + "]"


VECTORS = [
    ("rank-one [[1,2],[2,4]]^3",
     [[1, 2], [2, 4]], 3,
     [[25, 50], [50, 100]]),
    ("diagonal [[3,0],[0,-2]]^7",
     [[3, 0], [0, -2]], 7,
     [[2187, 0], [0, -128]]),
    ("all-ones [[1,1],[1,1]]^3",
     [[1, 1], [1, 1]], 3,
     [[4, 4], [4, 4]]),
    ("rational [[1/2,1/3],[0,1/4]]^11",
     [[Fraction(1, 2), Fraction(1, 3)], [0, Fraction(1, 4)]], 11,
     [[Fraction(1, 2048), Fraction(2047, 3145728)],
      [0, Fraction(1, 4194304)]]),
]


def validate():
    # Identity property, stable across all vectors: I*M == M*I == M, M^e*I == M^e.
    for name, raw, e, _ in VECTORS:
        M = to_matrix(raw)
        I = identity(len(M))
        assert matmul(I, M) == M and matmul(M, I) == M, f"identity failed: {name}"
        assert matmul(matpow(M, e), I) == matpow(M, e), f"identity^n failed: {name}"
    print("PASS identity: I*M == M*I == M and M^e*I == M^e for all vectors")

    # Associativity on identical-sized conformable matrices: (AB)C == A(BC),
    # exercised with A=M, B=M^2, C=M^3 for each vector (non-trivial products).
    for name, raw, _, _ in VECTORS:
        M = to_matrix(raw)
        A, B, C = M, matpow(M, 2), matpow(M, 3)
        assert matmul(matmul(A, B), C) == matmul(A, matmul(B, C)), name
        assert matmul(A, matmul(B, C)) == matpow(M, 6), name
    print("PASS associativity: (AB)C == A(BC) == M^6 for all vectors")

    # Deterministic vectors: every concrete final value reproduced exactly.
    for name, raw, e, expected_raw in VECTORS:
        got = matpow(to_matrix(raw), e)
        expected = to_matrix(expected_raw)
        print(f"expected {name} = {fmt(expected)}")
        print(f"computed {name} = {fmt(got)}")
        assert got == expected, f"MISMATCH: {name}"
        print(f"PASS {name}")

    # Bounded-runner overflow checks.
    try:
        matpow(to_matrix([[1]]), MAX_EXPONENT + 1)
        raise SystemExit("FAIL: exponent bound not enforced")
    except OverflowError:
        print("PASS overflow: exponent bound enforced")
    try:
        to_matrix([[0] * (MAX_DIM + 1)] * (MAX_DIM + 1))
        raise SystemExit("FAIL: dimension bound not enforced")
    except OverflowError:
        print("PASS overflow: dimension bound enforced")


if __name__ == "__main__":
    validate()
    print("ALL VALIDATIONS PASSED")
```

## Design Notes

- **Exact arithmetic**: every entry is coerced to `Fraction` at ingestion, so the rational vector's `2047/3145728` is produced symbolically — no rounding anywhere in the pipeline.
- **Exponentiation by squaring**: `matpow` decomposes `e` into set bits, squaring the base per shift; soundness rests on the associativity proof in the module docstring (finite-sum reordering plus distributivity over Q).
- **Overflow handling**: bounded runner with three guards — `MAX_DIM` and `MAX_EXPONENT` raise `OverflowError` at the boundary, and `_guard` aborts if any numerator/denominator exceeds `MAX_BITS` bits, since exact big-integer growth is the real overflow mode for `Fraction`.
- **Identity stability**: validated both as `I·M == M·I == M` and as `M^e·I == M^e` on every vector, so the identity property is checked on computed powers, not just inputs.

## Verified Output (`python3 matpow.py`, exit 0)

```
PASS identity: I*M == M*I == M and M^e*I == M^e for all vectors
PASS associativity: (AB)C == A(BC) == M^6 for all vectors
expected rank-one [[1,2],[2,4]]^3 = [[25, 50], [50, 100]]
computed rank-one [[1,2],[2,4]]^3 = [[25, 50], [50, 100]]
PASS rank-one [[1,2],[2,4]]^3
expected diagonal [[3,0],[0,-2]]^7 = [[2187, 0], [0, -128]]
computed diagonal [[3,0],[0,-2]]^7 = [[2187, 0], [0, -128]]
PASS diagonal [[3,0],[0,-2]]^7
expected all-ones [[1,1],[1,1]]^3 = [[4, 4], [4, 4]]
computed all-ones [[1,1],[1,1]]^3 = [[4, 4], [4, 4]]
PASS all-ones [[1,1],[1,1]]^3
expected rational [[1/2,1/3],[0,1/4]]^11 = [[1/2048, 2047/3145728], [0, 1/4194304]]
computed rational [[1/2,1/3],[0,1/4]]^11 = [[1/2048, 2047/3145728], [0, 1/4194304]]
PASS rational [[1/2,1/3],[0,1/4]]^11
PASS overflow: exponent bound enforced
PASS overflow: dimension bound enforced
ALL VALIDATIONS PASSED
```

Spot-checks against closed forms: rank-one gives `5^(3-1)·A = 25A = [[25,50],[50,100]]`; diagonal gives `3^7 = 2187`, `(-2)^7 = -128`; all-ones gives `2^(3-1)·J = 4J`; the rational off-diagonal is `(1/3)·Σ(1/2)^(10-k)(1/4)^k = 2047/3145728`. All match.

The mathematical artifact — exact matrix exponentiation by squaring with associativity proof, overflow bounds, identity validation, and all four deterministic vectors — is implemented in `matpow.py` and validated end-to-end with every assertion passing.