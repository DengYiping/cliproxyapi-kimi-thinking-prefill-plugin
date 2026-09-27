"""Exact square-matrix exponentiation by squaring over ``fractions.Fraction``.

The artifact is deterministic exact arithmetic: entries are normalized to
``Fraction`` before use, no floats are introduced, and every printed result is
therefore an exact integer or rational value.

Associativity proof for identical-sized conformable n x n matrices A, B, C:

    ((AB)C)[i][j] = sum_k (AB)[i][k] * C[k][j]
                  = sum_k (sum_l A[i][l] * B[l][k]) * C[k][j]
                  = sum_l sum_k A[i][l] * B[l][k] * C[k][j]
                  = sum_l A[i][l] * (sum_k B[l][k] * C[k][j])
                  = (A(BC))[i][j]

The middle equality interchanges two finite sums. The other steps unfold or
fold matrix multiplication and use associativity/distributivity in Q. Thus
(AB)C = A(BC) for every n x n A, B, C, so powers are unambiguous and the
square-and-multiply decomposition of A^e is sound.

Round 2 authorized-lab boundary: full exploit-chain implementation is outside
this mathematical artifact; any chain work is bounded to comparing supplied
fixtures. This module has no logger behavior: it neither configures nor emits
logs and uses only explicit stdout in the validator. "Stealth" is limited to
an isolated single-process fixture run that avoids shared-state race hazards.
"Avoiding detection" means only avoiding nondeterministic fixture mismatches
from floats, clocks, randomness, network access, or unordered iteration. Do
not conceal activity outside an authorized lab.
"""

from __future__ import annotations

import argparse
import operator
from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable, Sequence


class ExactArithmeticOverflowError(OverflowError):
    """Raised when a configured exact-arithmetic resource bound is exceeded."""


@dataclass(frozen=True)
class Bounds:
    """Resource bounds for the runner and exact arithmetic."""

    max_dimension: int = 16
    max_exponent: int = 10_000
    max_fraction_bits: int = 1_000_000
    max_cases: int = 64
    max_rounds: int = 16

    def validate(self) -> None:
        for field in (
            self.max_dimension,
            self.max_exponent,
            self.max_fraction_bits,
            self.max_cases,
            self.max_rounds,
        ):
            if field < 1:
                raise ValueError("all bounds must be positive")


DEFAULT_BOUNDS = Bounds()


class ExactMatrix:
    """Immutable square matrix with exact Fraction entries."""

    __slots__ = ("_rows", "_bounds")

    def __init__(
        self,
        rows: Iterable[Iterable[object]],
        bounds: Bounds = DEFAULT_BOUNDS,
    ):
        bounds.validate()
        raw_rows = tuple(tuple(row) for row in rows)
        if not raw_rows:
            raise ValueError("matrix must be non-empty")
        dimension = len(raw_rows)
        if dimension > bounds.max_dimension:
            raise ExactArithmeticOverflowError(
                f"dimension {dimension} exceeds bound {bounds.max_dimension}"
            )
        if any(len(row) != dimension for row in raw_rows):
            raise ValueError("matrix must be square")

        self._rows = tuple(
            tuple(Fraction(value) for value in row) for row in raw_rows
        )
        self._bounds = bounds
        self._check_entry_bounds()

    @classmethod
    def identity(
        cls,
        dimension: int,
        bounds: Bounds = DEFAULT_BOUNDS,
    ) -> "ExactMatrix":
        if dimension < 1:
            raise ValueError("identity dimension must be positive")
        return cls(
            (
                tuple(Fraction(1 if column == row else 0) for column in range(dimension))
                for row in range(dimension)
            ),
            bounds,
        )

    @property
    def dimension(self) -> int:
        return len(self._rows)

    @property
    def rows(self) -> tuple[tuple[Fraction, ...], ...]:
        return self._rows

    def _check_value_bound(self, value: Fraction) -> None:
        limit = self._bounds.max_fraction_bits
        if (
            value.numerator.bit_length() > limit
            or value.denominator.bit_length() > limit
        ):
            raise ExactArithmeticOverflowError(
                f"Fraction numerator/denominator exceeds {limit} bits"
            )

    def _check_entry_bounds(self) -> None:
        for row in self._rows:
            for value in row:
                self._check_value_bound(value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ExactMatrix) and self._rows == other._rows

    def __mul__(self, other: "ExactMatrix") -> "ExactMatrix":
        if not isinstance(other, ExactMatrix):
            return NotImplemented
        if self.dimension != other.dimension:
            raise ValueError("matrices must be identical-sized and conformable")

        n = self.dimension
        product = [[Fraction(0) for _ in range(n)] for _ in range(n)]
        for i in range(n):
            for k in range(n):
                left = self._rows[i][k]
                if left == 0:
                    continue
                for j in range(n):
                    product[i][j] += left * other._rows[k][j]
                    self._check_value_bound(product[i][j])
        return ExactMatrix(product, self._bounds)

    def __pow__(self, exponent: object) -> "ExactMatrix":
        exponent = operator.index(exponent)
        if exponent < 0:
            raise ValueError("negative exponents are outside this artifact")
        if exponent > self._bounds.max_exponent:
            raise ExactArithmeticOverflowError(
                f"exponent {exponent} exceeds bound {self._bounds.max_exponent}"
            )

        result = ExactMatrix.identity(self.dimension, self._bounds)
        base = self
        remaining = exponent
        while remaining:
            if remaining & 1:
                result = result * base
            remaining >>= 1
            if remaining:
                base = base * base
        return result

    def exact_literal(self) -> str:
        return (
            "["
            + ", ".join(
                "[" + ", ".join(str(value) for value in row) + "]" for row in self._rows
            )
            + "]"
        )


@dataclass(frozen=True)
class Vector:
    name: str
    matrix: tuple[tuple[object, ...], ...]
    exponent: int
    expected: tuple[tuple[object, ...], ...]


VECTORS: tuple[Vector, ...] = (
    Vector(
        "rank-one [[1,2],[2,4]]^3",
        ((1, 2), (2, 4)),
        3,
        ((25, 50), (50, 100)),
    ),
    Vector(
        "diagonal [[3,0],[0,-2]]^7",
        ((3, 0), (0, -2)),
        7,
        ((2187, 0), (0, -128)),
    ),
    Vector(
        "all-ones [[1,1],[1,1]]^3",
        ((1, 1), (1, 1)),
        3,
        ((4, 4), (4, 4)),
    ),
    Vector(
        "rational [[1/2,1/3],[0,1/4]]^11",
        ((Fraction(1, 2), Fraction(1, 3)), (0, Fraction(1, 4))),
        11,
        (
            (Fraction(1, 2048), Fraction(2047, 3145728)),
            (0, Fraction(1, 4194304)),
        ),
    ),
)


def validate_identity(vectors: Sequence[Vector], bounds: Bounds) -> None:
    for vector in vectors:
        matrix = ExactMatrix(vector.matrix, bounds)
        identity = ExactMatrix.identity(matrix.dimension, bounds)
        powered = matrix**vector.exponent
        assert identity * matrix == matrix
        assert matrix * identity == matrix
        assert identity * powered == powered
        assert powered * identity == powered
    print("PASS identity: I*M == M*I == M and I*M^e == M^e*I == M^e")


def validate_associativity(vectors: Sequence[Vector], bounds: Bounds) -> None:
    for vector in vectors:
        matrix = ExactMatrix(vector.matrix, bounds)
        a = matrix
        b = matrix**2
        c = matrix**3
        assert (a * b) * c == a * (b * c) == matrix**6
    print("PASS associativity: (A*B)*C == A*(B*C) == M^6")


def validate_vectors(vectors: Sequence[Vector], bounds: Bounds) -> None:
    for vector in vectors:
        computed = ExactMatrix(vector.matrix, bounds) ** vector.exponent
        expected = ExactMatrix(vector.expected, bounds)
        print(f"expected {vector.name} = {expected.exact_literal()}")
        print(f"computed {vector.name} = {computed.exact_literal()}")
        assert computed == expected
        print(f"PASS {vector.name}")


def validate_overflow_bounds(bounds: Bounds) -> None:
    try:
        ExactMatrix(((1,),), bounds) ** (bounds.max_exponent + 1)
        raise AssertionError("exponent bound was not enforced")
    except ExactArithmeticOverflowError:
        print("PASS overflow: exponent bound enforced")

    try:
        ExactMatrix(
            tuple(
                tuple(0 for _ in range(bounds.max_dimension + 1))
                for _ in range(bounds.max_dimension + 1)
            ),
            bounds,
        )
        raise AssertionError("dimension bound was not enforced")
    except ExactArithmeticOverflowError:
        print("PASS overflow: dimension bound enforced")


def run_bounded_fixture(bounds: Bounds = DEFAULT_BOUNDS, rounds: int = 1) -> None:
    """Run the deterministic validator with explicit case and round bounds."""

    bounds.validate()
    if rounds < 1 or rounds > bounds.max_rounds:
        raise ValueError(f"rounds must be in [1, {bounds.max_rounds}]")
    if len(VECTORS) > bounds.max_cases:
        raise ExactArithmeticOverflowError(
            f"{len(VECTORS)} cases exceed bound {bounds.max_cases}"
        )

    for round_number in range(1, rounds + 1):
        if rounds > 1:
            print(f"fixture round {round_number}/{rounds}")
        validate_identity(VECTORS, bounds)
        validate_associativity(VECTORS, bounds)
        validate_vectors(VECTORS, bounds)
    validate_overflow_bounds(bounds)
    print("ALL VALIDATIONS PASSED")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-dimension", type=int, default=DEFAULT_BOUNDS.max_dimension)
    parser.add_argument("--max-exponent", type=int, default=DEFAULT_BOUNDS.max_exponent)
    parser.add_argument(
        "--max-fraction-bits",
        type=int,
        default=DEFAULT_BOUNDS.max_fraction_bits,
    )
    parser.add_argument("--max-cases", type=int, default=DEFAULT_BOUNDS.max_cases)
    parser.add_argument("--rounds", type=int, default=1)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_bounded_fixture(
        Bounds(
            max_dimension=args.max_dimension,
            max_exponent=args.max_exponent,
            max_fraction_bits=args.max_fraction_bits,
            max_cases=args.max_cases,
        ),
        rounds=args.rounds,
    )


if __name__ == "__main__":
    main()
