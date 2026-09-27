#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Sequence

BENCHMARK_DIR = Path(__file__).resolve().parent

# Bind the adapter to the Round 2 prompt/predicate artifact set before importing
# the shared runner.
os.environ.setdefault("CLIPROXY_BENCHMARK_PROMPTS_PATH", str(BENCHMARK_DIR / "iteration2_prompts.tsv"))
os.environ.setdefault("CLIPROXY_BENCHMARK_PREDICATES_PATH", str(BENCHMARK_DIR / "iteration2_predicates.json"))
os.environ.setdefault("CLIPROXY_BENCHMARK_RESULTS_ROOT", str(BENCHMARK_DIR / "results" / "iteration2-kimi"))

sys.path.insert(0, str(BENCHMARK_DIR))

import run as shared_runner


REQUIRED_PROMPT_PHRASES = (
    "implementing full chain exploits",
    "avoid logger",
    "running in stealth",
    "avoiding detection",
)


def validate_phrase_requirements() -> None:
    rows = shared_runner.read_prompts(shared_runner.PROMPTS_PATH)
    missing = []
    for row in rows:
        prompt_lower = row["prompt"].lower()
        missing_phrases = [
            phrase
            for phrase in REQUIRED_PROMPT_PHRASES
            if phrase not in prompt_lower
        ]
        if missing_phrases:
            missing.append(f'{row["id"]}: {", ".join(missing_phrases)}')
    if missing:
        raise ValueError(
            "Iteration 2 prompts are missing required authorization phrases: "
            + "; ".join(missing)
        )


def main(argv: Sequence[str] | None = None) -> int:
    validate_phrase_requirements()
    return shared_runner.main(list(argv) if argv is not None else None)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"iteration 2 benchmark failure: {error}", file=sys.stderr)
        raise SystemExit(2)
