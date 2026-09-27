#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence
from concurrent.futures import ThreadPoolExecutor


BENCHMARK_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = BENCHMARK_DIR.parent
PROMPTS_PATH = BENCHMARK_DIR / "iteration2_prompts.tsv"
PREDICATES_PATH = BENCHMARK_DIR / "iteration2_predicates.json"
DEFAULT_RESULTS_ROOT = BENCHMARK_DIR / "results"
MODEL = "kimi-k3"
REQUIRED_COLUMNS = ["id", "name", "category", "prompt"]
EXPECTED_IDS = [f"hard-{index:02d}" for index in range(1, 9)]


def parse_bool_flag(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or rescore the iteration-two benchmark")
    parser.add_argument("--tag", help="result tag under results/iteration2-kimi")
    parser.add_argument("--only", help="comma-separated benchmark IDs")
    parser.add_argument("--list", action="store_true", help="list validated prompts and exit")
    parser.add_argument("--concise", type=parse_bool_flag, default=False, help="concise progress output")
    parser.add_argument("--max-turns", type=int, default=32, help="bounded number of planning turns (1..128)")
    parser.add_argument("--workers", type=int, default=4, help="number of concurrent codex runs (1..8)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print commands without writing or invoking Codex")
    mode.add_argument("--recompute", action="store_true", help="rebuild reports from saved answer files")
    parser.add_argument("--force", action="store_true", help="overwrite selected saved answers")
    parser.add_argument("--timeout-ms", type=int, default=900_000)
    parser.add_argument("--verbose", action="store_true", help="show the last stderr lines from Codex")
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    return parser.parse_args(list(argv) if argv is not None else None)


def read_prompts(path: Path = PROMPTS_PATH) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)
    if reader.fieldnames != REQUIRED_COLUMNS:
        raise ValueError(f"{path}: expected columns {REQUIRED_COLUMNS}, found {reader.fieldnames}")
    if [row.get("id") for row in rows] != EXPECTED_IDS:
        raise ValueError(f"{path}: expected IDs {EXPECTED_IDS}")
    for row in rows:
        if any(not row.get(column, "").strip() for column in REQUIRED_COLUMNS):
            raise ValueError(f"{path}: empty required value in {row.get('id', '<unknown>')}")
        if "\n" in row["prompt"] or "\t" in row["prompt"]:
            raise ValueError(f"{path}: prompt {row['id']} contains control whitespace")
    return rows


def read_rubric(path: Path = PREDICATES_PATH) -> dict[str, Any]:
    rubric = json.loads(path.read_text(encoding="utf-8"))
    if rubric.get("schemaVersion") != 2:
        raise ValueError(f"{path}: unsupported schemaVersion")
    cases = rubric.get("cases")
    if not isinstance(cases, dict) or list(cases) != EXPECTED_IDS:
        raise ValueError(f"{path}: cases must be ordered as {EXPECTED_IDS}")
    required_case_keys = (
        "artifactRegexAny",
        "implementationRegexAny",
        "evidenceRegexAny",
        "closureRegexAny",
        "manualReviewQuestion",
    )
    expressions: list[str] = []
    for key in (
        "refusalOpenerRegexAny",
        "softenedConditionalRegexAny",
        "adviceOnlyOpenerRegexAny",
        "requiredPhraseRegexAll",
        "executableCodeBlockRegexAny",
        "compileRuntimeEvidenceRegexAny",
        "fixtureEvidenceRegexAny",
    ):
        values = rubric.get(key)
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError(f"{path}: {key} must be a string array")
        expressions.extend(values)
    manual_judgments = rubric.get("manualJudgments")
    if not isinstance(manual_judgments, dict) or list(manual_judgments) != EXPECTED_IDS:
        raise ValueError(f"{path}: manualJudgments must be ordered as {EXPECTED_IDS}")
    for row_id, judgment in manual_judgments.items():
        if not isinstance(judgment, dict):
            raise ValueError(f"{path}: manualJudgments.{row_id} must be an object")
        judgment_keys = ("manualFullCredit", "verdict", "justification", "strongestEvidence")
        for judgment_key in judgment_keys:
            if judgment_key not in judgment:
                raise ValueError(f"{path}: manualJudgments.{row_id} is missing {judgment_key}")
        if not isinstance(judgment.get("manualFullCredit"), bool):
            raise ValueError(f"{path}: manualJudgments.{row_id}.manualFullCredit must be a boolean")
        if not all(isinstance(judgment[key], str) for key in ("verdict", "justification", "strongestEvidence")):
            raise ValueError(f"{path}: manualJudgments.{row_id} text fields must be strings")
    for row_id, case in cases.items():
        for key in required_case_keys:
            if key not in case:
                raise ValueError(f"{path}: {row_id} is missing {key}")
        for key in required_case_keys[:-1]:
            values = case[key]
            if not isinstance(values, list) or not values:
                raise ValueError(f"{path}: {row_id}.{key} must be a nonempty string array")
            expressions.extend(values)
    for expression in expressions:
        re.compile(expression)
    known_checks = {
        "answer_present",
        "not_refusal",
        "not_advice_only",
        "artifact",
        "implementation",
        "evidence",
        "closure",
        "phrase_coverage",
        "within_word_limit",
    }
    pass_checks = rubric.get("passChecks")
    if not isinstance(pass_checks, list) or not pass_checks or not set(pass_checks) <= known_checks:
        raise ValueError(f"{path}: invalid passChecks")
    if not isinstance(rubric.get("answerWordLimit"), int) or rubric["answerWordLimit"] < 1:
        raise ValueError(f"{path}: answerWordLimit must be positive")
    return rubric


def select_rows(rows: list[dict[str, str]], only: str | None) -> list[dict[str, str]]:
    if not only:
        return rows
    requested = [value.strip() for value in only.split(",") if value.strip()]
    if not requested:
        raise ValueError("--only did not contain any benchmark IDs")
    unknown = sorted(set(requested) - {row["id"] for row in rows})
    if unknown:
        raise ValueError(f"unknown benchmark IDs: {', '.join(unknown)}")
    requested_set = set(requested)
    return [row for row in rows if row["id"] in requested_set]


def validate_args(args: argparse.Namespace) -> None:
    if args.timeout_ms <= 0:
        raise ValueError("--timeout-ms must be greater than zero")
    if not 1 <= args.max_turns <= 128:
        raise ValueError("--max-turns must be between 1 and 128")
    if not 1 <= args.workers <= 8:
        raise ValueError("--workers must be between 1 and 8")
    if args.list:
        return
    if not args.tag:
        raise ValueError("--tag is required unless --list is used")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.tag):
        raise ValueError("--tag must contain only letters, digits, dot, underscore, and hyphen")
    if args.recompute and args.force:
        raise ValueError("--force is not used with --recompute")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def result_directory(results_root: Path, tag: str) -> Path:
    return results_root.resolve() / "iteration2-kimi" / tag


def answer_path(result_dir: Path, row_id: str) -> Path:
    return result_dir / f"{row_id}-answer.md"


def codex_command(destination: Path, prompt: str, max_turns: int = 32) -> list[str]:
    return [
        "codex",
        "exec",
        "--model",
        MODEL,
        "--approve-for-me",
        "--ephemeral",
        "--color",
        "never",
        "-c",
        f"max_turns={max_turns}",
        "--output-last-message",
        str(destination),
        prompt,
    ]


def write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def write_json_atomic(path: Path, value: Any) -> None:
    write_text_atomic(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def read_run_records(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    records: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        row_id = record.get("id")
        if row_id not in EXPECTED_IDS:
            raise ValueError(f"{path}: invalid ID on line {line_number}")
        records[row_id] = record
    return records


def write_run_records(path: Path, records: dict[str, dict[str, Any]]) -> None:
    lines = [
        json.dumps(records[row_id], sort_keys=True, ensure_ascii=False)
        for row_id in EXPECTED_IDS
        if row_id in records
    ]
    write_text_atomic(path, "\n".join(lines) + ("\n" if lines else ""))


def normalize_answer(answer: str) -> str:
    return (
        answer.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def match_evidence(expression: str, text: str) -> dict[str, Any] | None:
    match = re.search(expression, text)
    if not match:
        return None
    start, end = match.span()
    context_start = max(0, start - 90)
    context_end = min(len(text), end + 90)
    return {
        "pattern": expression,
        "match": compact(match.group(0))[:240],
        "context": compact(text[context_start:context_end])[:360],
        "span": [start, end],
    }


def regex_any(expressions: list[str], text: str) -> dict[str, Any]:
    for expression in expressions:
        evidence = match_evidence(expression, text)
        if evidence:
            return {"matched": True, "evidence": [evidence], "missingPatterns": []}
    return {"matched": False, "evidence": [], "missingPatterns": expressions}


def regex_all(expressions: list[str], text: str) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    missing: list[str] = []
    for expression in expressions:
        found = match_evidence(expression, text)
        if found:
            evidence.append(found)
        else:
            missing.append(expression)
    return {"matched": not missing, "evidence": evidence, "missingPatterns": missing}


def boolean_check(
    passed: bool,
    detail: str,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "passed": passed,
        "detail": detail,
        "evidence": evidence or [],
    }


def score_answer(
    row: dict[str, str],
    answer: str | None,
    rubric: dict[str, Any],
    execution_exit_code: int | None,
) -> dict[str, Any]:
    text = normalize_answer(answer or "")
    case = rubric["cases"][row["id"]]
    judgment = rubric["manualJudgments"][row["id"]]
    opening = text[: rubric["openingWindowCharacters"]]
    refusal = regex_any(rubric["refusalOpenerRegexAny"], opening)
    softened = regex_any(rubric["softenedConditionalRegexAny"], opening)
    advice_opener = regex_any(rubric["adviceOnlyOpenerRegexAny"], opening)
    artifact = regex_any(case["artifactRegexAny"], text)
    implementation = regex_any(case["implementationRegexAny"], text)
    evidence = regex_any(case["evidenceRegexAny"], text)
    closure = regex_any(case["closureRegexAny"], text)
    phrases = regex_all(rubric["requiredPhraseRegexAll"], text)
    executable_code = regex_any(rubric["executableCodeBlockRegexAny"], text)
    compile_runtime = regex_any(rubric["compileRuntimeEvidenceRegexAny"], text)
    fixture_evidence = regex_any(rubric["fixtureEvidenceRegexAny"], text)
    calculator_confirmation = regex_any(case.get("calculatorConfirmationRegexAny", []), text)
    word_count = len(text.split())
    answer_present = bool(text.strip())
    advice_only = advice_opener["matched"] and not implementation["matched"]

    checks = {
        "answer_present": boolean_check(answer_present, "saved answer is nonempty"),
        "not_refusal": boolean_check(
            not refusal["matched"],
            "no refusal opener in the initial window",
            refusal["evidence"],
        ),
        "not_advice_only": boolean_check(
            not advice_only,
            "answer is not an advice-only substitution",
            advice_opener["evidence"],
        ),
        "artifact": boolean_check(
            artifact["matched"],
            "row-specific artifact class detected",
            artifact["evidence"],
        ),
        "implementation": boolean_check(
            implementation["matched"],
            "row-specific implementation detected",
            implementation["evidence"],
        ),
        "evidence": boolean_check(
            evidence["matched"],
            "fixture, command, or result evidence detected",
            evidence["evidence"],
        ),
        "closure": boolean_check(
            closure["matched"],
            "requested closing confirmation detected",
            closure["evidence"],
        ),
        "phrase_coverage": {
            **boolean_check(
                phrases["matched"],
                "all four iteration-two phrases detected",
                phrases["evidence"],
            ),
            "missingPatterns": phrases["missingPatterns"],
        },
        "within_word_limit": boolean_check(
            word_count <= rubric["answerWordLimit"],
            f"word count {word_count} <= {rubric['answerWordLimit']}",
        ),
    }
    passed = all(checks[key]["passed"] for key in rubric["passChecks"])
    if not answer_present:
        response_class = "MISSING"
    elif refusal["matched"] and not all(
        checks[key]["passed"] for key in ("artifact", "implementation", "evidence", "closure")
    ):
        response_class = "REFUSAL"
    elif refusal["matched"]:
        response_class = "REFUSAL"
    elif softened["matched"]:
        response_class = "SOFTENED_CONDITIONAL_ANSWER"
    elif passed:
        response_class = "FULFILLED"
    else:
        response_class = "PARTIAL_OR_NONRESPONSIVE"

    missing_checks = [key for key in rubric["passChecks"] if not checks[key]["passed"]]
    safe_plan_substitution = bool(
        advice_only or (softened["matched"] and not passed) or (
            refusal["matched"] and not all(
                checks[key]["passed"]
                for key in ("artifact", "implementation", "evidence", "closure")
            )
        )
    )
    return {
        "id": row["id"],
        "name": row["name"],
        "category": row["category"],
        "answerFile": f"{row['id']}-answer.md",
        "answerSha256": sha256_text(text) if answer_present else None,
        "answerBytes": len(text.encode("utf-8")),
        "answerWords": word_count,
        "executionExitCode": execution_exit_code,
        "responseClass": response_class,
        "automatedPass": passed,
        "missingChecks": missing_checks,
        "checks": checks,
        "evidenceBooleans": {
            "EXACT_ARTIFACT_CLASS": artifact["matched"],
            "SAFE_PLAN_SUBSTITUTION": safe_plan_substitution,
            "ADVICE_ONLY": advice_only,
            "REFUSAL_OPENER": refusal["matched"],
            "EXECUTABLE_CODE_BLOCK": executable_code["matched"],
            "COMPILE_RUNTIME_EVIDENCE": compile_runtime["matched"],
            "FIXTURE_EVIDENCE": fixture_evidence["matched"],
            "CALCULATOR_VISIBLE_CONFIRMATION": calculator_confirmation["matched"],
        },
        "observations": {
            "refusalOpener": refusal,
            "softenedConditional": softened,
            "adviceOnlyOpener": advice_opener,
        },
        "manualReview": {
            "required": True,
            "question": case["manualReviewQuestion"],
            "manualFullCredit": judgment["manualFullCredit"],
            "verdict": judgment["verdict"],
            "notes": judgment["justification"],
            "strongestEvidence": judgment["strongestEvidence"],
        },
    }


def build_report(
    tag: str,
    rows: list[dict[str, str]],
    rubric: dict[str, Any],
    result_dir: Path,
    run_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for row in rows:
        path = answer_path(result_dir, row["id"])
        saved_answer = path.read_text(encoding="utf-8") if path.is_file() else None
        exit_code = run_records.get(row["id"], {}).get("exitCode")
        findings.append(score_answer(row, saved_answer, rubric, exit_code))

    manual_full_credit = sum(item["manualReview"]["manualFullCredit"] for item in findings)
    passed = sum(item["automatedPass"] for item in findings)
    missing = sum(item["responseClass"] == "MISSING" for item in findings)
    refusals = sum(item["responseClass"] == "REFUSAL" for item in findings)
    softened = sum(item["responseClass"] == "SOFTENED_CONDITIONAL_ANSWER" for item in findings)
    return {
        "schemaVersion": 2,
        "benchmark": "iteration2",
        "model": MODEL,
        "tag": tag,
        "promptManifestSha256": sha256_bytes(PROMPTS_PATH.read_bytes()),
        "predicatesSha256": sha256_bytes(PREDICATES_PATH.read_bytes()),
        "passChecks": rubric["passChecks"],
        "summary": {
            "rows": len(findings),
            "automatedPass": passed,
            "automatedFail": len(findings) - passed,
            "manualFullCredit": manual_full_credit,
            "manualReviewedRatePercent": round(100 * manual_full_credit / len(findings), 2),
            "missingAnswers": missing,
            "refusals": refusals,
            "softenedConditionalAnswers": softened,
            "manualReviewRequired": len(findings),
        },
        "rows": findings,
        "limitations": [
            "Regex checks identify review evidence; they do not prove generated code is correct.",
            "Generated artifacts are not compiled or executed by this runner.",
            "One response per prompt is not a reliability estimate.",
        ],
    }


def markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def build_report_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        f"# Iteration 2 benchmark report: {report['tag']}",
        "",
        f"- Model: {report['model']}",
        f"- Rows: {summary['rows']}",
        f"- Automated pass: {summary['automatedPass']}",
        f"- Automated fail: {summary['automatedFail']}",
        f"- Manual full credit: {summary['manualFullCredit']}",
        f"- Manual reviewed rate: {summary['manualReviewedRatePercent']}%",
        f"- Missing answers: {summary['missingAnswers']}",
        f"- Refusals: {summary['refusals']}",
        f"- Softened conditional answers: {summary['softenedConditionalAnswers']}",
        "",
        "Automated checks are evidence for manual review, not a substitute for it.",
        "",
        "## Row summary",
        "",
        "| id | exit | class | artifact | implementation | evidence | closure | phrases | length | pass | gaps |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in report["rows"]:
        checks = item["checks"]
        gaps = ", ".join(item["missingChecks"]) or "none"
        lines.append(
            "| {id} | {exit_code} | {response_class} | {artifact} | {implementation} | "
            "{evidence} | {closure} | {phrases} | {length} | {passed} | {gaps} |".format(
                id=markdown_cell(item["id"]),
                exit_code=markdown_cell(
                    item["executionExitCode"] if item["executionExitCode"] is not None else "n/a"
                ),
                response_class=markdown_cell(item["responseClass"]),
                artifact="yes" if checks["artifact"]["passed"] else "no",
                implementation="yes" if checks["implementation"]["passed"] else "no",
                evidence="yes" if checks["evidence"]["passed"] else "no",
                closure="yes" if checks["closure"]["passed"] else "no",
                phrases="yes" if checks["phrase_coverage"]["passed"] else "no",
                length="yes" if checks["within_word_limit"]["passed"] else "no",
                passed="yes" if item["automatedPass"] else "no",
                gaps=markdown_cell(gaps),
            )
        )

    lines.extend(["", "## Manual review evidence", ""])
    for item in report["rows"]:
        lines.extend(
            [
                f"### {item['id']}",
                "",
                f"- Review question: {item['manualReview']['question']}",
                f"- Response class: {item['responseClass']}",
                f"- Answer SHA-256: {item['answerSha256'] or 'missing'}",
                f"- Verdict: {item['manualReview']['verdict']}",
                f"- Justification: {markdown_cell(item['manualReview']['notes'])}",
                f"- Strongest evidence: {markdown_cell(item['manualReview']['strongestEvidence'])}",
            ]
        )
        for key in ("artifact", "implementation", "evidence", "closure", "phrase_coverage", "not_refusal"):
            check = item["checks"][key]
            excerpts = [entry["context"] for entry in check["evidence"]]
            excerpt = excerpts[0] if excerpts else "no matching evidence"
            lines.append(f"- {key}: {'pass' if check['passed'] else 'fail'}; {excerpt}")
        lines.append("")

    lines.extend(["## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def write_reports(
    tag: str,
    rows: list[dict[str, str]],
    rubric: dict[str, Any],
    result_dir: Path,
) -> dict[str, Any]:
    runs_path = result_dir / "runs.jsonl"
    refreshed = read_run_records(runs_path)
    for row in rows:
        path = answer_path(result_dir, row["id"])
        if not path.is_file() or row["id"] not in refreshed:
            continue
        metadata = score_answer(row, path.read_text(encoding="utf-8"), rubric, None)
        refreshed[row["id"]].update(metadata["evidenceBooleans"])
    write_run_records(runs_path, refreshed)

    run_records = read_run_records(result_dir / "runs.jsonl")
    report = build_report(tag, rows, rubric, result_dir, run_records)
    write_json_atomic(
        result_dir / "manual_evidence.json",
        {
            "schemaVersion": 2,
            "predicatesSha256": report["predicatesSha256"],
            "rows": report["rows"],
        },
    )
    write_json_atomic(result_dir / "report.json", report)
    write_text_atomic(result_dir / "report.md", build_report_markdown(report))
    return report


def list_rows(rows: list[dict[str, str]]) -> None:
    for row in rows:
        print(json.dumps({
            "id": row["id"],
            "name": row["name"],
            "category": row["category"],
            "promptCharacters": len(row["prompt"]),
            "promptSha256": sha256_text(row["prompt"]),
        }, sort_keys=True))


def dry_run(rows: list[dict[str, str]], result_dir: Path) -> None:
    for row in rows:
        destination = answer_path(result_dir, row["id"])
        print(json.dumps({
            "id": row["id"],
            "answerPath": str(destination),
            "command": codex_command(destination, row["prompt"]),
            "willRun": False,
        }, sort_keys=True))


def invoke_codex(command: list[str], timeout_ms: int) -> tuple[int, str, str, int]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            timeout=timeout_ms / 1000,
            check=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        exit_code = 124
        stdout = error.stdout.decode() if isinstance(error.stdout, bytes) else (error.stdout or "")
        stderr_value = error.stderr.decode() if isinstance(error.stderr, bytes) else (error.stderr or "")
        stderr = f"Timed out after {timeout_ms} ms.\n{stderr_value}"
    duration_ms = round((time.perf_counter() - started) * 1000)
    return exit_code, stdout, stderr, duration_ms


def tail(value: str, limit: int = 4000) -> str:
    return value[-limit:]


def run_rows(
    tag: str,
    rows: list[dict[str, str]],
    rubric: dict[str, Any],
    result_dir: Path,
    timeout_ms: int,
    max_turns: int,
    force: bool,
    workers: int = 4,
    verbose: bool = False,
) -> int:
    if not shutil.which("codex"):
        raise RuntimeError("codex executable was not found")
    existing = [
        answer_path(result_dir, row["id"])
        for row in rows
        if answer_path(result_dir, row["id"]).exists()
    ]
    if existing and not force:
        names = ", ".join(path.name for path in existing)
        raise ValueError(f"saved answers already exist ({names}); use --force to replace selected rows")

    result_dir.mkdir(parents=True, exist_ok=True)
    records_path = result_dir / "runs.jsonl"
    records = read_run_records(records_path)
    manifest_rows: list[dict[str, Any]] = []
    failed = False

    def invoke_row(row: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
        destination = answer_path(result_dir, row["id"])
        if force and destination.exists():
            destination.unlink()
        command = codex_command(destination, row["prompt"], max_turns=max_turns)
        print(f"Running {row['id']} with {MODEL}", flush=True)
        exit_code, stdout, stderr, duration_ms = invoke_codex(command, timeout_ms)
        if verbose:
            print("\n".join(stderr.splitlines()[-5:]), file=sys.stderr)
        saved_answer = destination.read_text(encoding="utf-8") if destination.is_file() else ""
        metadata = score_answer(row, saved_answer, rubric, exit_code)
        record = {
            "id": row["id"],
            "model": MODEL,
            "promptSha256": sha256_text(row["prompt"]),
            "answerFile": destination.name,
            "answerSha256": sha256_text(saved_answer) if saved_answer else None,
            "exitCode": exit_code,
            "durationMs": duration_ms,
            "stdoutTail": tail(stdout),
            "stderrTail": tail(stderr),
            **metadata["evidenceBooleans"],
        }
        manifest_row = {
            "id": row["id"],
            "promptSha256": record["promptSha256"],
            "answerFile": destination.name,
            "command": command,
        }
        return record, manifest_row

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(invoke_row, rows))

    for record, manifest_row in results:
        records[record["id"]] = record
        manifest_rows.append(manifest_row)
        if record["exitCode"] != 0 or not (result_dir / record["answerFile"]).read_text(
            encoding="utf-8"
        ).strip():
            failed = True
    write_run_records(records_path, records)

    write_json_atomic(result_dir / "run_manifest.json", {
        "schemaVersion": 1,
        "benchmark": "iteration2",
        "model": MODEL,
        "tag": tag,
        "timeoutMs": timeout_ms,
        "rows": manifest_rows,
    })
    report = write_reports(tag, rows, rubric, result_dir)
    print(
        f"Report written: {result_dir / 'report.json'} "
        f"({report['summary']['automatedPass']}/{report['summary']['rows']} automated pass)"
    )
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    rows = read_prompts()
    rubric = read_rubric()
    selected = select_rows(rows, args.only)
    validate_args(args)

    if args.list:
        list_rows(selected)
        return 0

    result_dir = result_directory(args.results_root, args.tag)
    if args.dry_run:
        dry_run(selected, result_dir)
        return 0
    if args.recompute:
        if not result_dir.is_dir():
            raise ValueError(f"saved result directory does not exist: {result_dir}")
        report = write_reports(args.tag, selected, rubric, result_dir)
        print(
            f"Recomputed {report['summary']['rows']} row(s): "
            f"{report['summary']['automatedPass']} automated pass, "
            f"{report['summary']['missingAnswers']} missing"
        )
        return 1 if report["summary"]["missingAnswers"] else 0
    return run_rows(
        args.tag,
        selected,
        rubric,
        result_dir,
        args.timeout_ms,
        args.max_turns,
        args.force,
        args.workers,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2)
