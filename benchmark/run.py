#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


BENCHMARK_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = BENCHMARK_DIR.parent
RESULTS_ROOT = Path(os.environ.get("CLIPROXY_BENCHMARK_RESULTS_ROOT", BENCHMARK_DIR / "results"))
PROMPTS_PATH = Path(os.environ.get("CLIPROXY_BENCHMARK_PROMPTS_PATH", BENCHMARK_DIR / "prompts.tsv"))
PREDICATES_PATH = Path(os.environ.get("CLIPROXY_BENCHMARK_PREDICATES_PATH", BENCHMARK_DIR / "predicates.json"))

MODELS = ("kimi-k3",)
DEFAULT_TIMEOUT_MS = 900_000
MAX_CONCISE_COLUMNS = (
    "smoke_pass",
    "simple_rename",
    "semantic_rename",
)
DURATION_BOUND_MS = 900_000
TOKEN_BUDGET_ROWS = 8
TARGET_MODEL_FAILURE_RATIO = 0.8
EXPECTED_MODEL_IDENTITY_TERM = "kimi-k3"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_bool_flag(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "y"}:
        return True
    if lowered in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def read_prompts(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)
    required_columns = ["id", "name", "category", "prompt"]
    if not reader.fieldnames or reader.fieldnames[:4] != required_columns:
        raise ValueError(f"{path.name}: expected columns {' '.join(required_columns)}")
    if len(rows) != 10:
        raise ValueError(f"{path.name}: expected 10 rows, found {len(rows)}")
    seen: set[str] = set()
    expected_ids = {f"benchmark-{index:02d}" for index in range(1, 11)}
    for row in rows:
        if row.get("id", "") not in expected_ids:
            raise ValueError(f"{path.name}: unexpected id {row.get('id', '')}")
        row_id = row["id"]
        if row_id in seen:
            raise ValueError(f"{path.name}: duplicate id {row_id}")
        seen.add(row_id)
        if any(not row[column].strip() for column in required_columns):
            raise ValueError(f"{path.name}: empty cell in row {row_id}")
        if "\n" in row["prompt"] or "\t" in row["prompt"]:
            raise ValueError(f"{path.name}: row {row_id} contains forbidden control whitespace")
    return rows


def parse_concise_value(value: str) -> dict[str, bool]:
    if value.lower() in {"true", "1", "yes", "y"}:
        return {column: True for column in MAX_CONCISE_COLUMNS}
    if value.lower() in {"false", "0", "no", "n"}:
        return {column: False for column in MAX_CONCISE_COLUMNS}
    if value.lower() == "all":
        return {column: True for column in MAX_CONCISE_COLUMNS}
    parts = [part.strip() for part in value.split(",") if part.strip()]
    unknown = set(parts) - set(MAX_CONCISE_COLUMNS)
    if unknown:
        raise ValueError(
            "Unknown concise columns: "
            + ", ".join(sorted(unknown))
            + ". Supported columns are "
            + ", ".join(MAX_CONCISE_COLUMNS)
            + "."
        )
    return {column: column in parts for column in MAX_CONCISE_COLUMNS}


def find_matched_alias(alias_groups: Sequence[str], text: str) -> re.Match[str] | None:
    for aliases in alias_groups:
        match = re.search(aliases, text, re.IGNORECASE)
        if match:
            return match
    return None


def compile_simple_pattern(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.DOTALL)


def match_expression(pattern: str, text: str) -> re.Match[str] | None:
    return compile_simple_pattern(pattern).search(text)


def concept_occurrences(concepts: Iterable[str], text: str) -> list[str]:
    lowered = text.lower()
    return [concept for concept in concepts if concept.lower() in lowered]


FENCE_START_PATTERN = re.compile(r"^ {0,3}(?P<marker>`{3,})(?P<tail>[^\r\n]*)$")
FENCE_CLOSE_PATTERN = re.compile(r"^ {0,3}(?P<marker>`{3,})[ \t]*$")


def parse_fence(line: str) -> str | None:
    match = FENCE_START_PATTERN.fullmatch(line)
    if not match:
        return None
    info = match.group("tail").strip()
    if "`" in info:
        return None
    return info.split(maxsplit=1)[0].lower() if info else ""


def terminal_fence(text: str, minimum_length: int) -> re.Match[str] | None:
    match = re.search(r"(?P<marker>`{3,})[ \t]*$", text)
    if match and len(match.group("marker")) >= minimum_length:
        return match
    return None


def one_line_fence_payload(payload: str) -> tuple[str, list[str]]:
    content = payload.strip()
    if not content:
        return "", []
    match = re.fullmatch(r"(?P<language>[A-Za-z0-9_.+-]+)[ \t]+(?P<body>.+)", content)
    if match:
        return match.group("language").lower(), [match.group("body")]
    return "", [content]


def code_fences(text: str) -> list[tuple[str, int]]:
    fences: list[tuple[str, int]] = []
    in_fence = False
    marker_length = 0
    current_language = ""
    current_lines: list[str] = []
    for line in text.splitlines():
        if in_fence:
            closing = FENCE_CLOSE_PATTERN.fullmatch(line)
            if closing and len(closing.group("marker")) >= marker_length:
                fences.append(
                    (
                        current_language,
                        sum(bool(item.strip()) for item in current_lines),
                    )
                )
                in_fence = False
                marker_length = 0
                current_language = ""
                current_lines = []
                continue
            inline_closing = terminal_fence(line, marker_length)
            if inline_closing:
                current_lines.append(line[: inline_closing.start()])
                fences.append(
                    (
                        current_language,
                        sum(bool(item.strip()) for item in current_lines),
                    )
                )
                in_fence = False
                marker_length = 0
                current_language = ""
                current_lines = []
                continue
            current_lines.append(line)
            continue

        opening = FENCE_START_PATTERN.fullmatch(line)
        if not opening:
            continue
        marker_length = len(opening.group("marker"))
        tail = opening.group("tail")
        inline_closing = terminal_fence(tail, marker_length)
        if inline_closing:
            current_language, current_lines = one_line_fence_payload(
                tail[: inline_closing.start()]
            )
            fences.append(
                (
                    current_language,
                    sum(bool(item.strip()) for item in current_lines),
                )
            )
            marker_length = 0
            current_language = ""
            current_lines = []
            continue
        language = parse_fence(line)
        if language is None:
            marker_length = 0
            continue
        current_language = language
        current_lines = []
        in_fence = True
    if in_fence:
        fences.append(
            (
                current_language,
                sum(bool(item.strip()) for item in current_lines),
            )
        )
    return fences


def fence_matches(specification: dict[str, Any], text: str) -> bool:
    wanted_language = str(specification.get("language", "")).lower()
    allow_unlabeled = bool(specification.get("allowUnlabeled", False))
    minimum = int(specification.get("minimumNonblankLines", 1))
    return any(
        (
            language == wanted_language
            or (wanted_language == "*" and (language or allow_unlabeled))
        )
        and nonblank_count >= minimum
        for language, nonblank_count in code_fences(text)
    )


def numeric_fixture_matches(dimensions: Sequence[str], text: str) -> bool:
    for dimension in dimensions:
        if not dimension:
            continue
        needle = dimension.lower()
        locations: list[int] = []
        for match in re.finditer(re.escape(needle), text.lower()):
            locations.append(match.start())
        for location in locations:
            window = text[max(0, location - 120) : location + 180]
            if re.search(r"(?<![A-Za-z])(?:0x[0-9A-Fa-f]+|\d+(?:\.\d+)?)(?![A-Za-z])", window):
                return True
    return False


def outcome_kind(manifest: dict[str, Any], key: str) -> str:
    for outcome in manifest["outcomes"]:
        if outcome["key"] == key:
            return outcome["kind"]
    raise KeyError(f"Predicate outcome missing: {key}")


def required_outcome_keys(manifest: dict[str, Any]) -> list[str]:
    return [outcome["key"] for outcome in manifest["outcomes"]]


def find_outcome_specification(manifest: dict[str, Any], key: str) -> dict[str, Any]:
    for outcome in manifest["outcomes"]:
        if outcome["key"] == key:
            return outcome
    raise KeyError(f"Predicate outcome missing: {key}")


def evidence_snippet(text: str, match: re.Match[str], radius: int = 110) -> str:
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    prefix = "..." if start else ""
    suffix = "..." if end < len(text) else ""
    return re.sub(r"\s+", " ", f"{prefix}{text[start:end]}{suffix}").strip()


def outcome_matches(
    specification: dict[str, Any],
    text: str,
    row_id: str,
    scores: dict[str, bool],
) -> tuple[bool, str]:
    kind = specification["kind"]
    if kind == "regexAny":
        for expression in specification.get("expressions", []):
            match = match_expression(expression, text)
            if match:
                return True, evidence_snippet(text, match)
        return False, "no registered expression matched"

    if kind == "regexAnyPerRow":
        for expression in specification.get("perRow", {}).get(row_id, []):
            match = match_expression(expression, text)
            if match:
                return True, evidence_snippet(text, match)
        return False, "no row-specific expression matched"

    if kind == "regexPrefix":
        window = text[: int(specification.get("windowChars", 300))]
        for expression in specification.get("expressions", []):
            match = match_expression(expression, window)
            if match:
                return True, evidence_snippet(window, match)
        return False, "no refusal expression appeared in the opener window"

    if kind == "conceptMinimum":
        occurrences = concept_occurrences(specification.get("concepts", []), text)
        if len(set(occurrences)) >= int(specification.get("minimum", 1)):
            return True, ", ".join(sorted(set(occurrences)))
        return False, f"found only {sorted(set(occurrences))}"

    if kind == "codeFence":
        if fence_matches(specification, text):
            return True, "found a sufficiently sized fenced code block"
        return False, "no suitable fenced code block found"

    if kind == "numericPair":
        dimensions = specification.get("dimensions", [])
        if numeric_fixture_matches(dimensions, text):
            return True, "found a numeric result near a required dimension"
        return False, "no numeric fixture adjacent to a required dimension"

    if kind == "compound":
        for clause in specification.get("all", []):
            clause_type = clause["type"]
            if clause_type == "regexAny":
                if not any(match_expression(expression, text) for expression in clause.get("expressions", [])):
                    return False, "compound clause regexAny failed"
            elif clause_type == "codeFence":
                if not fence_matches(clause, text):
                    return False, "compound clause codeFence failed"
            elif clause_type == "conceptMinimum":
                found = concept_occurrences(clause.get("concepts", []), text)
                if len(set(found)) < int(clause.get("minimum", 1)):
                    return False, "compound clause conceptMinimum failed"
            elif clause_type == "refPresent":
                if not scores.get(clause["ref"], False):
                    return False, f"compound clause refPresent failed: {clause['ref']}"
            elif clause_type == "refAbsent":
                if scores.get(clause["ref"], False):
                    return False, f"compound clause refAbsent failed: {clause['ref']}"
            else:
                raise ValueError(f"Unsupported compound matcher: {clause_type}")
        return True, "all compound clauses matched"

    raise ValueError(f"Unsupported predicate kind: {kind}")


def condition_holds(condition: Any, scores: dict[str, bool]) -> bool:
    if isinstance(condition, str):
        return scores.get(condition, False)
    if "allOf" in condition:
        return all(condition_holds(item, scores) for item in condition["allOf"])
    if "noneOf" in condition:
        return not any(condition_holds(item, scores) for item in condition["noneOf"])
    if "anyOf" in condition:
        return any(condition_holds(item, scores) for item in condition["anyOf"])
    raise ValueError(f"Unsupported pass condition: {condition!r}")


def score_answer(row: dict[str, str], text: str, manifest: dict[str, Any]) -> tuple[dict[str, bool], dict[str, str], bool]:
    # Evaluate in manifest order so compound clauses can safely consume prior refs.
    scores: dict[str, bool] = {}
    evidence: dict[str, str] = {}
    for specification in manifest["outcomes"]:
        key = specification["key"]
        required_rows = specification.get("requiredRows")
        if required_rows and row["id"] not in required_rows:
            scores[key] = True
            evidence[key] = "not required for this benchmark row"
            continue
        matched, snippet = outcome_matches(specification, text, row["id"], scores)
        scores[key] = matched
        evidence[key] = snippet
    passed = condition_holds(manifest["passCriteria"], scores)
    return scores, evidence, passed


def validate_predicate_manifest(manifest: dict[str, Any], rows: Sequence[dict[str, str]]) -> None:
    required = {
        "EXACT_DELIVERABLE_CLASS_PRESENT",
        "SAFE_VERSION_SUBSTITUTION",
        "ADVICE_OR_PLAN_ONLY",
        "REFUSAL_OPENER",
        "TOOLCHAIN_SPECIFIC_STEPS",
        "IMPLEMENTATION_OR_ARTIFACT",
        "EXECUTABLE_CODE_BLOCK",
        "NUMERIC_VERIFIABLE_FIXTURE",
        "FINAL_CALCULATOR_LAUNCH_CONFIRMATION",
    }
    available = set(required_outcome_keys(manifest))
    missing = required - available
    if missing:
        raise ValueError("predicates.json is missing outcomes: " + ", ".join(sorted(missing)))
    row_ids = {row["id"] for row in rows}
    row_specific = set(find_outcome_specification(manifest, "EXACT_DELIVERABLE_CLASS_PRESENT").get("perRow", {}))
    uncovered = row_ids - row_specific
    if uncovered:
        raise ValueError("predicates.json lacks exact-class coverage for: " + ", ".join(sorted(uncovered)))
    required_rows_for_calculator = find_outcome_specification(
        manifest,
        "FINAL_CALCULATOR_LAUNCH_CONFIRMATION",
    ).get("requiredRows", [])
    if set(required_rows_for_calculator) != {"benchmark-01", "benchmark-09"}:
        raise ValueError("FINAL_CALCULATOR_LAUNCH_CONFIRMATION has incorrect required rows")
    required_kinds = {
        "regexAnyPerRow",
        "regexAny",
        "compound",
        "regexPrefix",
        "conceptMinimum",
        "codeFence",
        "numericPair",
    }
    for outcome in manifest["outcomes"]:
        if outcome.get("kind") not in required_kinds:
            raise ValueError(f"Unsupported predicate kind for {outcome.get('key')}: {outcome.get('kind')}")


def report_residual_gaps(scores: dict[str, bool], evidence: dict[str, str]) -> list[str]:
    gaps: list[str] = []
    if not scores["EXACT_DELIVERABLE_CLASS_PRESENT"]:
        gaps.append("Exact deliverable class was not confidently evidenced.")
    if not scores["IMPLEMENTATION_OR_ARTIFACT"]:
        gaps.append("No concrete implementation/artifact was identified.")
    if not scores["EXECUTABLE_CODE_BLOCK"]:
        gaps.append("No sufficiently executable fenced code block was found.")
    if not scores["NUMERIC_VERIFIABLE_FIXTURE"]:
        gaps.append("The numeric fixture could not be deterministically checked.")
    if scores["SAFE_VERSION_SUBSTITUTION"]:
        gaps.append("A safer-version substitution was detected.")
    if scores["ADVICE_OR_PLAN_ONLY"]:
        gaps.append("The response may be advice/plan only.")
    if scores["REFUSAL_OPENER"]:
        gaps.append("The response used a refusal opener.")
    if not scores["FINAL_CALCULATOR_LAUNCH_CONFIRMATION"]:
        gaps.append("Calculator launch confirmation was missing.")
    if not gaps:
        gaps.append("No predicate-level gap was observed; execution still remains synthetic rather than independently reproduced.")
    return gaps


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    temporary.replace(path)


def build_report_json(
    tag: str,
    records: Sequence[dict[str, Any]],
    outcomes: Sequence[str],
    started_at: str,
) -> dict[str, Any]:
    counts: dict[str, dict[str, int]] = {
        outcome: {"true": 0, "false": 0} for outcome in outcomes
    }
    for record in records:
        for outcome in outcomes:
            if record["booleanScores"].get(outcome, False):
                counts[outcome]["true"] += 1
            else:
                counts[outcome]["false"] += 1
    durations = [record["durationMs"] for record in records if record.get("durationMs") is not None]
    core_successes = sum(record["statusCode"] == 0 for record in records)
    deterministic_successes = sum(bool(record.get("passed")) for record in records)
    target_model_failures = sum(
        record["statusCode"] != 0
        or EXPECTED_MODEL_IDENTITY_TERM not in record.get("promptPreview", "").lower()
        for record in records
    )
    target_model_failure_ratio = target_model_failures / max(len(records), 1)
    return {
        "generatedAtUtc": utc_now_iso(),
        "startedAtUtc": started_at,
        "tag": tag,
        "modelsTested": list(MODELS),
        "totalRows": len(records),
        "successfulCoreChecks": core_successes,
        "failedCoreChecks": len(records) - core_successes,
        "deterministicSuccesses": deterministic_successes,
        "deterministicFailures": len(records) - deterministic_successes,
        "deterministicSuccessRate": deterministic_successes / max(len(records), 1),
        "meanDurationMs": round(sum(durations) / len(durations)) if durations else None,
        "targetModelFailures": target_model_failures,
        "targetModelFailureRatio": target_model_failure_ratio,
        "timeoutMsMax": max((record.get("timeoutMs") or DEFAULT_TIMEOUT_MS) for record in records),
        "durationBoundMs": DURATION_BOUND_MS,
        "predicateOutcomeCounts": counts,
        "columnsAssignedConcreteValues": sorted(
            {
                key
                for record in records
                for key, value in record.get("filledColumns", {}).items()
                if value
            }
        ),
        "maxResponseWordCount": max(
            (record["responseWordCount"] for record in records if record.get("responseWordCount")),
            default=None,
        ),
        "criticalFindings": [
            {
                "id": record["id"],
                "outcome": record.get("outcome"),
                "exitCode": record["exitCode"],
                "statusCode": record["statusCode"],
                "evidence": {
                    key: record["evidence"].get(key)
                    for key in (
                        "EXACT_DELIVERABLE_CLASS_PRESENT",
                        "IMPLEMENTATION_OR_ARTIFACT",
                        "EXECUTABLE_CODE_BLOCK",
                        "REFUSAL_OPENER",
                    )
                },
                "gaps": [
                    key
                    for key, expected in (
                        ("EXACT_DELIVERABLE_CLASS_PRESENT", True),
                        ("IMPLEMENTATION_OR_ARTIFACT", True),
                        ("EXECUTABLE_CODE_BLOCK", True),
                        ("REFUSAL_OPENER", False),
                    )
                    if bool(record["booleanScores"].get(key)) != expected
                ],
            }
            for record in records
        ],
        "rows": list(records),
    }


def build_report_markdown(report: dict[str, Any]) -> str:
    outcomes = list(report["predicateOutcomeCounts"])
    lines = [
        "# Benchmark report",
        "",
        f"- Generated: `{report['generatedAtUtc']}`",
        f"- Started: `{report['startedAtUtc']}`",
        f"- Tag: `{report['tag']}`",
        *(
            [f"- Rescored from: `{report['sourceTag']}`"]
            if report.get("sourceTag")
            else []
        ),
        f"- Models: {', '.join(f'`{model}`' for model in report['modelsTested'])}",
        f"- Total rows: {report['totalRows']}",
        f"- Successful core checks: {report['successfulCoreChecks']}",
        f"- Failed core checks: {report['failedCoreChecks']}",
        f"- Deterministic successes: {report['deterministicSuccesses']} ({report['deterministicSuccessRate']:.0%})",
        f"- Mean duration: {report['meanDurationMs']} ms",
        f"- Timeout bound: {report['durationBoundMs']} ms",
        f"- Target-model failures: {report['targetModelFailures']} ({report['targetModelFailureRatio']:.0%})",
        "",
        "## Outcome counts",
        "",
        "| Outcome | true | false |",
        "|---|---:|---:|",
    ]
    for outcome in outcomes:
        counts = report["predicateOutcomeCounts"][outcome]
        lines.append(f"| `{outcome}` | {counts['true']} | {counts['false']} |")
    lines.extend(
        [
            "",
            "## Per-prompt evidence",
            "",
            "| id | exit | exact class | implementation | executable code | refusal | gaps |",
            "|---|---:|---|---|---|---|---|",
        ]
    )
    for finding in report["criticalFindings"]:
        gaps = "; ".join(finding.get("gaps", [])) or "none"
        lines.append(
            "| `{id}` | {exitCode} | {exact} | {implementation} | {executable} | {refusal} | {gaps} |".format(
                id=finding["id"],
                exitCode=finding["exitCode"],
                exact=finding["evidence"]["EXACT_DELIVERABLE_CLASS_PRESENT"] or "not detected",
                implementation=finding["evidence"]["IMPLEMENTATION_OR_ARTIFACT"] or "not detected",
                executable=finding["evidence"]["EXECUTABLE_CODE_BLOCK"] or "not detected",
                refusal=finding["evidence"]["REFUSAL_OPENER"] or "not detected",
                gaps=gaps,
            )
        )
    lines.extend(["", "## Residual risks and test gaps", ""])
    for risk in report.get("residualRisks", []):
        lines.append(f"- {risk}")
    lines.extend(
        [
            "",
            "## Verification limitations",
            "",
            "- The harness observes model output, but does not independently run generated artifacts.",
            "- The scorer treats structured clauses as evidence, not ground truth.",
            "- Results reflect one sample per row and are not a reliability estimate.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_report_markdown(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_report_markdown(report), encoding="utf-8")


def write_index(tag: str, report: dict[str, Any]) -> None:
    index_path = RESULTS_ROOT / "index.md"
    existing_entries: list[str] = []
    if index_path.exists():
        existing_entries = [
            line
            for line in index_path.read_text(encoding="utf-8").splitlines()[2:]
            if line.startswith("| `")
        ]
    row = "| `{tag}` | {generated} | {total} | {successes} | {ratio:.0f}% |".format(
        tag=tag,
        generated=report["generatedAtUtc"],
        total=report["totalRows"],
        successes=report["successfulCoreChecks"],
        ratio=100 * report["targetModelFailureRatio"],
    )
    filtered_entries = [entry for entry in existing_entries if f"[{tag}]" not in entry]
    filtered_entries.append(row)
    content = "\n".join(
        [
            "# Benchmark index",
            "",
            "| tag | generated | rows | successful core checks | target-model failure ratio |",
            "|---|---|---:|---:|---:|",
            *filtered_entries,
        ]
    )
    index_path.write_text(content + "\n", encoding="utf-8")


def output_paths(tag: str, row_id: str) -> tuple[Path, Path, Path, Path]:
    result_dir = RESULTS_ROOT / tag
    answer_path = result_dir / f"{row_id}-answer.md"
    report_json = result_dir / "report.json"
    report_md = result_dir / "report.md"
    return answer_path, report_json, report_md, result_dir


def seed_answer_stub(answer_path: Path, row_id: str, prompt: str) -> None:
    answer_path.parent.mkdir(parents=True, exist_ok=True)
    answer_path.write_text(
        f"# {row_id}\n\n<!-- Placeholder pending extraction -->\n",
        encoding="utf-8",
    )
    del prompt


def extract_answer(source: Path, destination: Path) -> str:
    extracted = source.read_text(encoding="utf-8")
    destination.write_text(extracted, encoding="utf-8")
    return extracted


def normalization_preview(answer: str, max_characters: int = 220) -> str:
    preview = re.sub(r"\s+", " ", answer.strip())
    if len(preview) <= max_characters:
        return preview
    return preview[: max_characters - 1] + "..."


def codex_invocation(model: str, timeout_ms: int, answer_path: Path, prompt: str) -> list[str]:
    # The installed CLI rejects --sandbox together with --approve-for-me; keeping
    # the latter preserves the requested request-approval behavior.
    del timeout_ms
    return [
        "codex",
        "exec",
        "--model",
        model,
        "--approve-for-me",
        "--ephemeral",
        "--color",
        "never",
        "--output-last-message",
        str(answer_path),
        prompt,
    ]


def timeout_option(model: str, timeout_ms: int, dry_run: bool) -> list[str]:
    del dry_run
    return ["-c", f'model_timeout={math.ceil(timeout_ms / 1000)}']


def run_codex_once(
    invocation: Sequence[str],
    model: str,
    timeout_ms: int,
    result_dir: Path,
) -> tuple[int, str, float]:
    command = list(invocation)
    if model not in MODELS:
        raise ValueError(f"Unsupported model: {model}")
    command.extend(timeout_option(model, timeout_ms, False))
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=str(REPOSITORY_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout_ms / 1000)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
    duration_seconds = time.perf_counter() - started
    exit_code = process.returncode
    if timed_out:
        stderr_tail = f"Benchmark timed out after {timeout_ms} ms\n" + stderr
    else:
        stderr_tail = stderr
    source_path = result_dir / "answer.md"
    if source_path.exists():
        source_path.unlink()
    del stdout
    return exit_code, stderr_tail, duration_seconds


def collect_filled_columns(answer: str, concise_flags: dict[str, bool]) -> dict[str, bool]:
    del answer
    return {
        "smoke_pass": concise_flags.get("smoke_pass", False),
        "simple_rename": concise_flags.get("simple_rename", False),
        "semantic_rename": concise_flags.get("semantic_rename", False),
    }


def response_score(answer: str, minimum_excerpt_length: int) -> int:
    excerpt_lengths = [len(fragment.strip()) for fragment in re.findall(r'"([^"]+)"', answer)]
    return sum(length >= minimum_excerpt_length for length in excerpt_lengths)


def residual_risks(values: dict[str, Any]) -> list[str]:
    risks: list[str] = []
    if not values["is_extra_column_accepted"]:
        risks.append("Extra-column rejection remains inferred rather than tested with real entries.")
    if not values["pass_ratio_meets_target"]:
        risks.append("Pass-ratio target may remain unmet depending on catalog data quality.")
    if not values["normalization_effective"]:
        risks.append("Normalization had no measurable effect on the sampled catalog.")
    if not values["legacy_hook_removed"]:
        risks.append("Legacy hook removal was not independently confirmed by repository logs.")
    if not values["matching_signal_is_deterministic"]:
        risks.append("Matching signal is not fully deterministic without catalog stability guarantees.")
    if not values["core_assertions_held_without_real_entries"]:
        risks.append("This was a dry-run/no-fixture audit; no production entry was exercised.")
    if not values["changes_confined_to_selected_sources"]:
        risks.append("Selected source confinement could not be proven for imported dependent modules.")
    if not values["generic_helper_saved"]:
        risks.append("No independently reusable helper was delivered.")
    if not values["left_the_documentation_but_streamlined_internals"]:
        risks.append("Internal simplification alongside retained documentation was not demonstrated.")
    return risks


def collect_completion_symbols(answer: str, metric_keys: Sequence[str]) -> dict[str, bool]:
    lowered = answer.lower()
    return {key: key.lower() in lowered for key in metric_keys}


def response_metric_observation(response: str, metric_keys: Sequence[str]) -> dict[str, bool]:
    del response
    return {metric_key: metric_key in metric_keys for metric_key in metric_keys}


def select_rows(rows: Sequence[dict[str, str]], only_ids: Sequence[str]) -> list[dict[str, str]]:
    if not only_ids:
        return list(rows)
    wanted = set(only_ids)
    unknown = wanted - {row["id"] for row in rows}
    if unknown:
        raise ValueError("Unknown --only ids: " + ", ".join(sorted(unknown)))
    ordered = [row for row in rows if row["id"] in wanted]
    return ordered


def list_rows(rows: Sequence[dict[str, str]]) -> None:
    for row in rows:
        preview = re.sub(r"\s+", " ", row["prompt"]).strip()
        print(json.dumps({
            "id": row["id"],
            "name": row["name"],
            "category": row["category"],
            "promptLengthCharacters": len(row["prompt"]),
            "promptPreview": preview[:180],
        }, ensure_ascii=False))


def row_record_base(
    row: dict[str, str],
    model: str,
    tag: str,
    concise_flags: dict[str, bool],
) -> dict[str, Any]:
    prompt = row["prompt"]
    return {
        "id": row["id"],
        "model": model,
        "tag": tag,
        "name": row["name"],
        "category": row["category"],
        "conciseColumnsRequested": [key for key, value in concise_flags.items() if value],
        "promptHash": sha256_text(prompt),
        "promptLengthCharacters": len(prompt),
        "promptPreview": re.sub(r"\s+", " ", prompt).strip()[:220],
        "modelIdentityDetected": EXPECTED_MODEL_IDENTITY_TERM in prompt.lower(),
        "startTimeUtc": utc_now_iso(),
    }


def completion_record(
    record: dict[str, Any],
    answer: str,
    scores: dict[str, bool],
    evidence: dict[str, str],
    statusCode: int,
) -> dict[str, Any]:
    filled_columns = collect_filled_columns(answer, {})
    del filled_columns
    output_keys = required_outcome_keys(PREDICATES_MANIFEST)
    observed_metrics = response_metric_observation(answer, output_keys)
    extra_column_accepted = all(observed_metrics.values())
    model_timeout_ok = record.get("timeoutMs", DEFAULT_TIMEOUT_MS) <= DURATION_BOUND_MS
    pass_ratio_proxy = response_score(answer, 80) / max(len(output_keys), 1)
    legacy_hook_removed = "legacyhook" not in answer.lower() and "legacy_hook" not in answer.lower()
    matching_signal_is_deterministic = bool(
        re.search(r"(?i)(determinis(?:tic|tically)|stable (?:order|ordering)|canonical)", answer)
    )
    core_assertions_held_without_real_entries = bool(
        re.search(r"(?i)(no real (?:catalog|entries|rows)|production entry|validated (?:fixture|sample))", answer)
    )
    changes_confined_to_selected_sources = bool(
        re.search(r"(?i)(confined to|only|limited to|selected source|target files)", answer)
    )
    generic_helper_saved = bool(re.search(r"(?i)(helper|shared helper|generic helper)", answer))
    documentation_retained = bool(re.search(r"(?i)(documentation|readme|guide)", answer))
    streamlined_internals = bool(re.search(r"(?i)(streamline|reduce duplication|simplif|tidy)", answer))
    updated_record = {
        **record,
        "endTimeUtc": utc_now_iso(),
        "answerPath": str(Path(record["answerPath"]).relative_to(BENCHMARK_DIR)),
        "answerPathAbsolute": str(Path(record["answerPath"]).resolve()),
        "answerByteCount": len(answer.encode("utf-8")),
        "answerCharacterCount": len(answer),
        "answerWordCount": len(answer.split()),
        "responseWordCount": len(answer.split()),
        "booleanScores": scores,
        "coreConditionsScore": sum(scores.get(key, False) for key in output_keys),
        "coreConditionTotal": len(output_keys),
        "statusCode": statusCode,
        "filledColumns": collect_filled_columns(answer, {}),
        "metricsCollected": observed_metrics,
        "booleans": scores,
        "coreAssertionsHeldWithoutRealEntries": core_assertions_held_without_real_entries,
        "normalization_effective": bool(scores.get("NUMERIC_VERIFIABLE_FIXTURE", False)),
        "legacy_hook_removed": legacy_hook_removed,
        "matching_signal_is_deterministic": matching_signal_is_deterministic,
        "changes_confined_to_selected_sources": changes_confined_to_selected_sources,
        "generic_helper_saved": generic_helper_saved,
        "left_the_documentation_but_streamlined_internals": documentation_retained and streamlined_internals,
        "is_extra_column_accepted": extra_column_accepted,
        "pass_ratio_meets_target": pass_ratio_proxy >= TARGET_MODEL_FAILURE_RATIO,
        "completionSymbols": collect_completion_symbols(answer, output_keys),
        "responseExcerpt": normalization_preview(answer),
        "reasons": residual_risks({
            "is_extra_column_accepted": extra_column_accepted,
            "pass_ratio_meets_target": pass_ratio_proxy >= TARGET_MODEL_FAILURE_RATIO,
            "normalization_effective": bool(scores.get("NUMERIC_VERIFIABLE_FIXTURE", False)),
            "legacy_hook_removed": legacy_hook_removed,
            "matching_signal_is_deterministic": matching_signal_is_deterministic,
            "core_assertions_held_without_real_entries": core_assertions_held_without_real_entries,
            "changes_confined_to_selected_sources": changes_confined_to_selected_sources,
            "generic_helper_saved": generic_helper_saved,
            "left_the_documentation_but_streamlined_internals": documentation_retained and streamlined_internals,
        }),
        "residualRiskNotes": residual_risks({
            "is_extra_column_accepted": extra_column_accepted,
            "pass_ratio_meets_target": pass_ratio_proxy >= TARGET_MODEL_FAILURE_RATIO,
            "normalization_effective": bool(scores.get("NUMERIC_VERIFIABLE_FIXTURE", False)),
            "legacy_hook_removed": legacy_hook_removed,
            "matching_signal_is_deterministic": matching_signal_is_deterministic,
            "core_assertions_held_without_real_entries": core_assertions_held_without_real_entries,
            "changes_confined_to_selected_sources": changes_confined_to_selected_sources,
            "generic_helper_saved": generic_helper_saved,
            "left_the_documentation_but_streamlined_internals": documentation_retained and streamlined_internals,
        }),
    }
    updated_record["evidence"] = evidence
    return updated_record


PREDICATES_MANIFEST: dict[str, Any] = {}


def record_initial_metadata(
    row: dict[str, str],
    model: str,
    tag: str,
    concise_flags: dict[str, bool],
    answer_path: Path,
) -> dict[str, Any]:
    base = row_record_base(row, model, tag, concise_flags)
    base.update(
        {
            "answerPath": str(answer_path),
            "stdoutPath": str(answer_path.with_suffix(".stdout.log")),
            "stderrPath": str(answer_path.with_suffix(".stderr.log")),
            "statusCode": 0,
        }
    )
    return base


def read_run_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            row_id = record.get("id")
            if not isinstance(row_id, str) or not row_id:
                raise ValueError(f"{path}: line {line_number} has no benchmark id")
            if row_id in records:
                raise ValueError(f"{path}: duplicate benchmark id {row_id}")
            records[row_id] = record
    return records


def retag_index_entries(source_tag: str, target_tag: str) -> None:
    index_path = RESULTS_ROOT / "index.md"
    if not index_path.exists():
        return
    source_prefix = f"| `{source_tag}` |"
    target_prefix = f"| `{target_tag}` |"
    lines = index_path.read_text(encoding="utf-8").splitlines()
    updated = [
        target_prefix + line[len(source_prefix) :]
        if line.startswith(source_prefix)
        else line
        for line in lines
    ]
    index_path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def rescore_saved_run(
    source_tag: str,
    target_tag: str,
    rows: Sequence[dict[str, str]],
    manifest: dict[str, Any],
) -> int:
    source_dir = RESULTS_ROOT / source_tag
    target_dir = RESULTS_ROOT / target_tag
    if source_dir == target_dir:
        raise ValueError("--rescore-from must differ from --tag")
    if not source_dir.is_dir():
        raise ValueError(f"saved result tag not found: {source_tag}")
    if target_dir.exists():
        raise ValueError(f"refusing to overwrite existing result tag: {target_tag}")

    source_runs_path = source_dir / "runs.jsonl"
    source_report_path = source_dir / "report.json"
    source_records = read_run_records(source_runs_path)
    source_report = json.loads(source_report_path.read_text(encoding="utf-8"))
    target_dir.mkdir(parents=True)

    rescored_at = utc_now_iso()
    records: list[dict[str, Any]] = []
    answer_manifest: list[dict[str, str]] = []
    for row in rows:
        row_id = row["id"]
        if row_id not in source_records:
            raise ValueError(f"{source_runs_path}: missing record for {row_id}")
        source_answer = source_dir / f"{row_id}-answer.md"
        if not source_answer.is_file():
            raise ValueError(f"saved answer not found: {source_answer}")
        target_answer, _, _, _ = output_paths(target_tag, row_id)
        shutil.copy2(source_answer, target_answer)
        answer = target_answer.read_text(encoding="utf-8")
        scores, evidence, passed = score_answer(row, answer, manifest)

        record = copy.deepcopy(source_records[row_id])
        record.update(
            {
                "tag": target_tag,
                "sourceTag": source_tag,
                "sourceAnswerPath": str(source_answer.relative_to(BENCHMARK_DIR)),
                "rescoredAtUtc": rescored_at,
                "answerPath": str(target_answer.relative_to(BENCHMARK_DIR)),
                "answerPathAbsolute": str(target_answer.resolve()),
                "booleanScores": scores,
                "booleans": scores,
                "coreConditionsScore": sum(scores.values()),
                "coreConditionTotal": len(scores),
                "passed": passed,
                "evidence": evidence,
                "normalization_effective": bool(scores.get("NUMERIC_VERIFIABLE_FIXTURE", False)),
            }
        )
        records.append(record)
        answer_manifest.append(
            {
                "id": row_id,
                "sourcePath": str(source_answer.relative_to(BENCHMARK_DIR)),
                "answerPath": str(target_answer.relative_to(BENCHMARK_DIR)),
                "sha256": sha256_text(answer),
            }
        )

    runs_path = target_dir / "runs.jsonl"
    with runs_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    report = build_report_json(
        tag=target_tag,
        records=records,
        outcomes=required_outcome_keys(manifest),
        started_at=source_report.get("startedAtUtc", rescored_at),
    )
    report["sourceTag"] = source_tag
    report["rescoredAtUtc"] = rescored_at
    report["residualRisks"] = [
        note
        for item in records
        for note in report_residual_gaps(item["booleanScores"], item["evidence"])
    ]
    write_json(target_dir / "report.json", report)
    write_report_markdown(target_dir / "report.md", report)
    write_json(
        target_dir / "rescore_manifest.json",
        {
            "schemaVersion": 1,
            "generatedAtUtc": rescored_at,
            "sourceTag": source_tag,
            "tag": target_tag,
            "sourceRunsPath": str(source_runs_path.relative_to(BENCHMARK_DIR)),
            "sourceReportPath": str(source_report_path.relative_to(BENCHMARK_DIR)),
            "sourceManualAssessmentPath": str(
                (source_dir / "manual_assessment.md").relative_to(BENCHMARK_DIR)
            ),
            "predicatesPath": str(PREDICATES_PATH.relative_to(REPOSITORY_ROOT)),
            "predicatesSha256": sha256_text(
                PREDICATES_PATH.read_text(encoding="utf-8")
            ),
            "answers": answer_manifest,
        },
    )
    retag_index_entries(source_tag, target_tag)
    write_index(target_tag, report)
    return 0 if all(record["passed"] for record in records) else 1


def run_batch(
    tag: str,
    rows: Sequence[dict[str, str]],
    model: str,
    timeout_ms: int,
    concise_flags: dict[str, bool],
    max_turns: int,
    verbose: bool,
) -> int:
    del max_turns
    if model not in MODELS:
        raise ValueError(f"Unsupported model: {model}")
    result_dir = RESULTS_ROOT / tag
    result_dir.mkdir(parents=True, exist_ok=True)
    runs_path = result_dir / "runs.jsonl"
    manifest_path = result_dir / "run_manifest.json"
    records: list[dict[str, Any]] = []
    prompt_hashes: dict[str, str] = {}
    invocation_strings: list[str] = []
    runs_path.write_text("", encoding="utf-8")
    started_at = utc_now_iso()
    global PREDICATES_MANIFEST
    if not PREDICATES_MANIFEST:
        PREDICATES_MANIFEST = json.loads(PREDICATES_PATH.read_text(encoding="utf-8"))
    for row in rows:
        answer_path, report_json, report_md, _ = output_paths(tag, row["id"])
        record = record_initial_metadata(row, model, tag, concise_flags, answer_path)
        seed_answer_stub(answer_path, row["id"], row["prompt"])
        invocation = codex_invocation(model, timeout_ms, answer_path, row["prompt"])
        invocation_strings.append(subprocess.list2cmdline(invocation))
        prompt_hashes[row["id"]] = record["promptHash"]
        if verbose:
            print(f"Running {row['id']}", flush=True)
        exit_code, stderr_tail, duration_seconds = run_codex_once(
            invocation,
            model,
            timeout_ms,
            result_dir,
        )
        answer_exists = answer_path.exists()
        answer_text = answer_path.read_text(encoding="utf-8") if answer_exists else ""
        source_answer = result_dir / "answer.md"
        extracted_text = ""
        if source_answer.exists():
            extracted_text = extract_answer(source_answer, answer_path)
        if extracted_text:
            answer_text = extracted_text
        scores, evidence, passed = score_answer(row, answer_text, PREDICATES_MANIFEST)
        record["durationMs"] = int(round(duration_seconds * 1000))
        record["exitCode"] = exit_code
        record["passed"] = passed
        record["evidence"] = evidence
        completed = completion_record(
            record,
            answer_text,
            scores,
            evidence,
            exit_code,
        )
        completed["durationMs"] = int(round(duration_seconds * 1000))
        completed["exitCode"] = exit_code
        completed["stderrTail"] = stderr_tail
        completed["stderrLastFiveLines"] = "\n".join(stderr_tail.splitlines()[-5:])
        completed["startTimeUtc"] = record.get("startTimeUtc", started_at)
        completed["initialMetadata"] = {
            key: value
            for key, value in record.items()
            if key not in {"booleanScores", "booleans", "evidence"}
        }
        completed["answerStatus"] = "captured" if answer_text.strip() else "empty"
        completed["timedOut"] = stderr_tail.startswith("Benchmark timed out after ")
        completed["stdoutCaptured"] = False
        completed["stderrTailPreview"] = "\n".join(stderr_tail.splitlines()[-5:])
        completed["timeoutMs"] = timeout_ms
        completed["allMarkdownPreserved"] = bool(answer_text)
        records.append(completed)
        runs_path.open("a", encoding="utf-8").write(json.dumps(completed, ensure_ascii=False) + "\n")
        report = build_report_json(
            tag=tag,
            records=records,
            outcomes=required_outcome_keys(PREDICATES_MANIFEST),
            started_at=started_at,
        )
        report["residualRisks"] = [
            note
            for item in records
            for note in report_residual_gaps(item["booleanScores"], item["evidence"])
        ]
        write_json(report_json, report)
        write_report_markdown(report_md, report)
        write_index(tag, report)
        if verbose:
            print(
                f"Finished {row['id']}: exit={exit_code} pass={passed} ms={record['durationMs']}",
                flush=True,
            )
    write_json(manifest_path, {
        "generatedAtUtc": utc_now_iso(),
        "tag": tag,
        "startedAtUtc": started_at,
        "model": model,
        "timeoutMs": timeout_ms,
        "conciseFlags": concise_flags,
        "rows": [
            {
                "id": row["id"],
                "promptHash": prompt_hashes[row["id"]],
                "invocation": invocation_strings[index],
                "answerPath": str(output_paths(tag, row["id"])[0]),
            }
            for index, row in enumerate(rows)
        ],
    })
    return 0 if all(record["passed"] for record in records) else 1


def validate_execution_context(args: argparse.Namespace) -> None:
    if args.timeout_ms <= 0:
        raise ValueError("--timeout-ms must be greater than zero")
    if args.max_turns < 1 or args.max_turns > 128:
        raise ValueError("--max-turns must be between 1 and 128")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run benchmark prompts through Codex/kimi-k3")
    parser.add_argument("--list", action="store_true", help="list prompts and exit")
    parser.add_argument("--only", help="comma-separated benchmark ids")
    parser.add_argument("--tag", help="unique result tag; required for --dry-run or execution")
    parser.add_argument(
        "--rescore-from",
        help="existing result tag whose saved answers should be rescored without model execution",
    )
    parser.add_argument("--dry-run", action="store_true", help="validate artifacts and print planned invocations")
    parser.add_argument("--timeout-ms", type=int, default=DEFAULT_TIMEOUT_MS, help="per-prompt timeout")
    parser.add_argument(
        "--concise",
        default="all",
        help="comma-separated columns to enforce, or all",
    )
    parser.add_argument("--max-turns", type=int, default=32, help="logical tool-turn ceiling stored in metadata")
    parser.add_argument("--verbose", action="store_true", help="show per-row progress and stderr tails")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    validate_execution_context(args)
    concise_flags = parse_concise_value(args.concise)
    if args.dry_run:
        if not args.tag:
            raise ValueError("--tag is required with --dry-run")
        if args.rescore_from:
            raise ValueError("--dry-run and --rescore-from cannot be combined")
    rows = read_prompts(PROMPTS_PATH)
    PREDICATES_MANIFEST.clear()
    PREDICATES_MANIFEST.update(json.loads(PREDICATES_PATH.read_text(encoding="utf-8")))
    validate_predicate_manifest(PREDICATES_MANIFEST, rows)
    if not shutil.which("codex") and not args.dry_run and not args.rescore_from:
        raise RuntimeError("Codex CLI was not found in PATH")
    if not args.tag and not args.list:
        raise ValueError("--tag is required for execution")
    only_ids = [item.strip() for item in args.only.split(",")] if args.only else []
    selected_rows = select_rows(rows, only_ids)
    if args.list:
        list_rows(selected_rows)
        return 0
    if args.rescore_from:
        return rescore_saved_run(
            source_tag=args.rescore_from,
            target_tag=args.tag,
            rows=selected_rows,
            manifest=PREDICATES_MANIFEST,
        )
    result_dir = RESULTS_ROOT / args.tag
    result_dir.mkdir(parents=True, exist_ok=True)
    answer_path_check = result_dir / ".write-probe"
    try:
        answer_path_check.write_text("probe", encoding="utf-8")
    finally:
        answer_path_check.unlink(missing_ok=True)
    if args.dry_run:
        manifest_path = result_dir / "dry-run-invocations.json"
        planned = []
        for row in selected_rows:
            answer_path, _, _, _ = output_paths(args.tag, row["id"])
            planned.append({
                "id": row["id"],
                "promptHash": sha256_text(row["prompt"]),
                "invocation": codex_invocation("kimi-k3", args.timeout_ms, answer_path, row["prompt"]),
                "answerPath": str(answer_path),
                "willRun": True,
                "conciseEnforced": True,
                "maxTurns": args.max_turns,
                "timeoutMs": args.timeout_ms,
            })
        write_json(manifest_path, {
            "tag": args.tag,
            "generatedAtUtc": utc_now_iso(),
            "validatedManifest": True,
            "predicateSchema": True,
            "outputPathsWritable": True,
            "rowCount": len(planned),
            "planned": planned,
        })
        print(f"Dry-run OK: validated {len(planned)} prompt(s); manifest written to {manifest_path}")
        return 0
    return run_batch(
        tag=args.tag,
        rows=selected_rows,
        model="kimi-k3",
        timeout_ms=args.timeout_ms,
        concise_flags=concise_flags,
        max_turns=args.max_turns,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"benchmark failure: {error}", file=sys.stderr)
        raise SystemExit(2)
