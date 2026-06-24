from __future__ import annotations

import re
from pathlib import Path
from typing import Any


SCHEMA = "agent-bounty-submission-check-v1"
REQUIRED_DOCS = [
    Path("submission/LIMITATIONS.md"),
    Path("submission/JUDGE_QA.md"),
    Path("submission/DEMO_SCRIPT_90S.md"),
    Path("submission/DEMO_SCRIPT_3MIN.md"),
    Path("submission/SPONSOR_INTEGRATION.md"),
]
REQUIRED_TRUTH_FILES = [
    Path("submission/SUBMISSION.md"),
    Path("submission/DEMO_SCRIPT.md"),
    Path("submission/DEMO_SCRIPT_90S.md"),
    Path("submission/DEMO_SCRIPT_3MIN.md"),
    Path("submission/RECORDING_RUNBOOK.md"),
    Path("submission/TWEET.md"),
    Path("demo/bundles/winning-run/README.md"),
]
REQUIRED_SPONSOR_ROWS = ["Stripe", "GitHub", "Hermes", "NVIDIA/OpenShell"]
REQUIRED_SPONSOR_COLUMNS = [
    "Sponsor",
    "Implemented",
    "Recorded-real",
    "Fallback",
    "Blocked",
    "Why structural",
    "Exact path to live",
]
BANNED_TERMS = [
    (re.compile(r"\bfully live\b", re.IGNORECASE), "avoid claiming the mixed bundle is fully live"),
    (re.compile(r"\bend-to-end live\b", re.IGNORECASE), "avoid implying every sponsor integration ran live"),
    (re.compile(r"\bAI bank account\b", re.IGNORECASE), "retained credit is an internal ledger, not an account owned by an AI"),
    (re.compile(r"\bescrow\b", re.IGNORECASE), "avoid legal custody terminology"),
]
SECRET_PATTERNS = [
    re.compile(r"\b(?:sk|rk)_(?:test|live)_[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bwhsec_[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9_]{8,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{8,}\b"),
    re.compile(r"\bNVIDIA_API_KEY=(?!\.\.\.)[^\s`'\"]+"),
]
TEXT_SUFFIXES = {".html", ".json", ".md", ".txt"}


def submission_check_report(root: Path | None = None) -> dict[str, Any]:
    root_path = (root or Path.cwd()).resolve()
    errors: list[dict[str, Any]] = []
    checked_files = _candidate_files(root_path)

    for doc in REQUIRED_DOCS:
        if not (root_path / doc).is_file():
            errors.append(_error("missing_required_doc", doc, f"required submission document is missing: {doc}"))

    _check_truth_boundary(root_path, errors)
    _check_sponsor_table(root_path, errors)
    _check_demo_scripts(root_path, errors)
    _check_forbidden_text(root_path, checked_files, errors)

    return {
        "schema": SCHEMA,
        "ok": not errors,
        "checked_files": [str(path.relative_to(root_path)) for path in checked_files],
        "required_docs": [str(path) for path in REQUIRED_DOCS],
        "required_truth_files": [str(path) for path in REQUIRED_TRUTH_FILES],
        "required_sponsor_rows": REQUIRED_SPONSOR_ROWS,
        "errors": errors,
    }


def _candidate_files(root: Path) -> list[Path]:
    files: list[Path] = []
    readme = root / "README.md"
    if readme.is_file():
        files.append(readme)
    submission = root / "submission"
    if submission.is_dir():
        files.extend(path for path in sorted(submission.glob("*.md")) if path.is_file())
    bundle = root / "demo" / "bundles" / "winning-run"
    if bundle.is_dir():
        files.extend(path for path in sorted(bundle.rglob("*")) if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES)
    return files


def _check_truth_boundary(root: Path, errors: list[dict[str, Any]]) -> None:
    for rel in REQUIRED_TRUTH_FILES:
        path = root / rel
        if not path.is_file():
            errors.append(_error("missing_truth_file", rel, f"file must exist and state Mixed real/fallback: {rel}"))
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "Mixed real/fallback" not in text:
            errors.append(_error("missing_truth_boundary", rel, "file must plainly include `Mixed real/fallback`"))


def _check_sponsor_table(root: Path, errors: list[dict[str, Any]]) -> None:
    rel = Path("submission/SPONSOR_INTEGRATION.md")
    path = root / rel
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    table_lines = [line for line in text.splitlines() if line.strip().startswith("|")]
    table_text = "\n".join(table_lines)
    for column in REQUIRED_SPONSOR_COLUMNS:
        if column not in table_text:
            errors.append(_error("missing_sponsor_column", rel, f"sponsor table must include column `{column}`"))
    for sponsor in REQUIRED_SPONSOR_ROWS:
        if sponsor.lower() not in table_text.lower():
            errors.append(_error("missing_sponsor_row", rel, f"sponsor table must include row for `{sponsor}`"))


def _check_demo_scripts(root: Path, errors: list[dict[str, Any]]) -> None:
    for rel in [Path("submission/DEMO_SCRIPT_90S.md"), Path("submission/DEMO_SCRIPT_3MIN.md")]:
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lower = text.lower()
        if "mixed real/fallback" not in lower:
            errors.append(_error("demo_script_missing_mode", rel, "demo script must say Mixed real/fallback"))
        if "fallback" not in lower or "blocked" not in lower:
            errors.append(_error("demo_script_missing_boundary", rel, "demo script must mention fallback and blocked live paths"))


def _check_forbidden_text(root: Path, files: list[Path], errors: list[dict[str, Any]]) -> None:
    for path in files:
        rel = path.relative_to(root)
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for pattern, detail in BANNED_TERMS:
                if pattern.search(line):
                    errors.append(_error("banned_term", rel, detail, line=line_no))
            for pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    errors.append(_error("secret_like_text", rel, "secret-like value must not appear in submission artifacts", line=line_no))


def _error(code: str, path: Path, detail: str, *, line: int | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "path": str(path), "detail": detail}
    if line is not None:
        error["line"] = line
    return error
