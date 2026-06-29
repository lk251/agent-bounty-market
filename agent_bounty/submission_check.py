from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SCHEMA = "agent-bounty-submission-check-v1"
ENTRY_SCHEMA = "agent-bounty-entry-check-v1"
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
    (re.compile(r"\bidle-only\b", re.IGNORECASE), "use original/superficial/final verifier wording instead of the old idle-only shorthand"),
    (re.compile(r"\breward exceeds maximum bounty amount\b", re.IGNORECASE), "use project spending-cap language instead of the old internal reward error"),
    (re.compile(r"\bminimum remaining reserve would be violated\b", re.IGNORECASE), "use reserve-floor language instead of the old internal reserve error"),
    (
        re.compile(r"\bPolicy and budget select one bounded bounty while alternatives can decline\b", re.IGNORECASE),
        "use clear project-agent funding and verifier-backed work language",
    ),
    (re.compile(r"\balternatives can decline\b", re.IGNORECASE), "use clear project-agent funding and verifier-backed work language"),
]
SECRET_PATTERNS = [
    re.compile(r"\b(?:sk|rk)_(?:test|live)_[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bwhsec_[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9_]{8,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{8,}\b"),
    re.compile(r"\bNVIDIA_API_KEY=(?!\.\.\.)[^\s`'\"]+"),
]
TEXT_SUFFIXES = {".html", ".json", ".md", ".txt"}
ENTRY_REQUIRED_DOCS = [
    Path("submission/ENTRY_REQUIREMENTS.md"),
    Path("submission/TWEET.md"),
    Path("submission/DISCORD_SUBMISSION.md"),
    Path("submission/TYPEFORM_FINAL.md"),
    Path("submission/VIDEO_METADATA.md"),
    Path("submission/SUBMISSION_PORTAL_CHECKLIST.md"),
    Path("submission/OPERATOR_FINALIZATION.md"),
]
ENTRY_TRUTH_FILES = [
    Path("submission/TWEET.md"),
    Path("submission/DISCORD_SUBMISSION.md"),
    Path("submission/TYPEFORM_FINAL.md"),
    Path("submission/VIDEO_METADATA.md"),
    Path("submission/SUBMISSION_PORTAL_CHECKLIST.md"),
    Path("submission/OPERATOR_FINALIZATION.md"),
]
ENTRY_PLACEHOLDER_RE = re.compile(r"\[[A-Z][A-Z0-9_ /.-]*\]|\b(?:TODO|TBD|TO_BE_FILLED)\b")
TWEET_BLOCK_RE = re.compile(
    r"^### (?P<name>.+?)\n"
    r"Status: (?P<status>[^\n]+)\n"
    r"Character count: (?P<count>[0-9]+)\n"
    r"```tweet\n(?P<body>.*?)\n```",
    re.MULTILINE | re.DOTALL,
)
TWEET_LIMIT = 280
ULTRA_SHORT_LIMIT = 180


def submission_check_report(
    root: Path | None = None,
    *,
    entry: bool = False,
    final: bool = False,
    prepost: bool = False,
    state: Path | None = None,
) -> dict[str, Any]:
    root_path = (root or Path.cwd()).resolve()
    errors: list[dict[str, Any]] = []
    checked_files = _candidate_files(root_path)
    if final or prepost:
        entry = True

    for doc in REQUIRED_DOCS:
        if not (root_path / doc).is_file():
            errors.append(_error("missing_required_doc", doc, f"required submission document is missing: {doc}"))

    _check_truth_boundary(root_path, errors)
    _check_sponsor_table(root_path, errors)
    _check_demo_scripts(root_path, errors)
    _check_forbidden_text(root_path, checked_files, errors)
    entry_report = _check_entry_package(root_path, final=final, prepost=prepost, state=state, errors=errors) if entry else None

    result = {
        "schema": SCHEMA,
        "ok": not errors,
        "mode": "entry-final" if final else "entry-prepost" if prepost else "entry-draft" if entry else "standard",
        "checked_files": [path.relative_to(root_path).as_posix() for path in checked_files],
        "required_docs": [path.as_posix() for path in REQUIRED_DOCS],
        "required_truth_files": [path.as_posix() for path in REQUIRED_TRUTH_FILES],
        "required_sponsor_rows": REQUIRED_SPONSOR_ROWS,
        "errors": errors,
    }
    if entry_report is not None:
        result["entry"] = entry_report
    return result


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


def _check_entry_package(
    root: Path,
    *,
    final: bool,
    prepost: bool,
    state: Path | None,
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    placeholders: list[dict[str, Any]] = []
    for doc in ENTRY_REQUIRED_DOCS:
        path = root / doc
        if not path.is_file():
            errors.append(_error("missing_entry_doc", doc, f"required entry document is missing: {doc}"))
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        placeholders.extend(_placeholder_locations(doc, text))

    for rel in ENTRY_TRUTH_FILES:
        path = root / rel
        if path.is_file() and "Mixed real/fallback" not in path.read_text(encoding="utf-8", errors="replace"):
            errors.append(_error("entry_missing_truth_boundary", rel, "entry-facing file must include `Mixed real/fallback`"))

    tweet_variants = _check_tweets(root, errors)
    release = _check_entry_release_claims(root, errors)
    _check_video_metadata(root, errors)
    _check_judge_qa_completion(root, errors)

    operator_report = _check_operator_state(root, final=final, prepost=prepost, state=state, errors=errors)

    if final and placeholders and state is None:
        for placeholder in placeholders:
            errors.append(_error("final_placeholder", Path(placeholder["path"]), f"final mode cannot contain placeholder `{placeholder['placeholder']}`", line=placeholder["line"]))

    return {
        "schema": ENTRY_SCHEMA,
        "mode": "final" if final else "prepost" if prepost else "draft",
        "required_docs": [path.as_posix() for path in ENTRY_REQUIRED_DOCS],
        "tweet_variants": tweet_variants,
        "release": release,
        "operator": operator_report,
        "placeholder_count": len(placeholders),
        "placeholders": placeholders[:50],
    }


def _check_tweets(root: Path, errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rel = Path("submission/TWEET.md")
    path = root / rel
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    variants = extract_tweet_variants(text)
    if len(variants) < 4:
        errors.append(_error("tweet_variant_count", rel, "tweet package must include single post, two thread posts, and ultra-short fallback"))
    heading_text = "\n".join(variant["name"].lower() for variant in variants)
    for required in ["single", "thread 1", "thread 2", "ultra"]:
        if required not in heading_text:
            errors.append(_error("tweet_variant_missing", rel, f"tweet package missing `{required}` variant"))
    for variant in variants:
        line = variant["line"]
        body = variant["body"]
        actual = tweet_character_count(body)
        if actual != variant["declared_count"]:
            errors.append(_error("tweet_character_count_mismatch", rel, f"{variant['name']} declares {variant['declared_count']} but actual count is {actual}", line=line))
        if actual > TWEET_LIMIT:
            errors.append(_error("tweet_too_long", rel, f"{variant['name']} is {actual} characters; limit is {TWEET_LIMIT}", line=line))
        if "ultra" in variant["name"].lower() and tweet_character_count(_before_url_placeholder(body)) > ULTRA_SHORT_LIMIT:
            errors.append(_error("tweet_ultra_short_too_long", rel, f"{variant['name']} must be under {ULTRA_SHORT_LIMIT} characters before URL", line=line))
        if "@NousResearch" not in body:
            errors.append(_error("tweet_missing_nous_tag", rel, f"{variant['name']} must include @NousResearch", line=line))
        if "Mixed real/fallback" not in body:
            errors.append(_error("tweet_missing_truth_boundary", rel, f"{variant['name']} must include Mixed real/fallback", line=line))
    return [
        {"name": variant["name"], "status": variant["status"], "declared_count": variant["declared_count"], "actual_count": tweet_character_count(variant["body"])}
        for variant in variants
    ]


def extract_tweet_variants(text: str) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    for match in TWEET_BLOCK_RE.finditer(text):
        variants.append(
            {
                "name": match.group("name").strip(),
                "status": match.group("status").strip(),
                "declared_count": int(match.group("count")),
                "body": match.group("body"),
                "line": text.count("\n", 0, match.start()) + 1,
            }
        )
    return variants


def tweet_character_count(text: str) -> int:
    from .operator_submission import x_character_count

    return x_character_count(text)


def _check_operator_state(
    root: Path,
    *,
    final: bool,
    prepost: bool,
    state: Path | None,
    errors: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not (final or prepost or state is not None):
        return None
    if state is None:
        state = root / ".demo" / "operator-submission.json"
    else:
        state = state.expanduser()
        if not state.is_absolute():
            state = root / state
    if not state.is_file():
        errors.append(_error("operator_state_missing", Path(".demo/operator-submission.json"), "operator state is required for prepost/final checks"))
        return {
            "schema": "agent-bounty-operator-state-report-v1",
            "ok": False,
            "mode": "final" if final else "prepost",
            "errors": [{"code": "operator_state_missing", "path": ".demo/operator-submission.json", "detail": "operator state is required"}],
        }
    from .operator_submission import operator_state_report

    report = operator_state_report(state, root=root, mode="final" if final else "prepost")
    if not report.get("ok"):
        for error in report.get("errors", []):
            errors.append(_error("operator_" + str(error.get("code", "invalid")), Path(str(error.get("path", state))), str(error.get("detail", "operator state invalid"))))
    return report


def _before_url_placeholder(text: str) -> str:
    return text.split("[REPO_URL]", 1)[0].split("[TWEET_URL]", 1)[0].rstrip()


def _check_entry_release_claims(root: Path, errors: list[dict[str, Any]]) -> dict[str, Any]:
    release_manifest = _read_json(root / "submission" / "RELEASE_MANIFEST.json")
    bundle_manifest = _read_json(root / "demo" / "bundles" / "winning-run" / "manifest.json")
    release_tag = str(release_manifest.get("release_tag") or "")
    release_truth = str(release_manifest.get("truth_status") or "")
    release_bundle_digest = str(release_manifest.get("bundle_digest") or "")
    bundle_digest = str(bundle_manifest.get("bundle_digest") or "")
    if release_truth != "Mixed real/fallback":
        errors.append(_error("entry_release_truth_mismatch", Path("submission/RELEASE_MANIFEST.json"), "release manifest truth status must be Mixed real/fallback"))
    if release_bundle_digest != bundle_digest:
        errors.append(_error("entry_bundle_digest_mismatch", Path("submission/RELEASE_MANIFEST.json"), "release manifest bundle digest must match current bundle manifest"))

    portal = root / "submission" / "SUBMISSION_PORTAL_CHECKLIST.md"
    discord = root / "submission" / "DISCORD_SUBMISSION.md"
    combined = ""
    for path in [portal, discord]:
        if path.is_file():
            combined += "\n" + path.read_text(encoding="utf-8", errors="replace")
    if release_tag and release_tag not in combined:
        errors.append(_error("entry_release_tag_missing", Path("submission/SUBMISSION_PORTAL_CHECKLIST.md"), f"entry package must mention release tag `{release_tag}`"))
    if bundle_digest and bundle_digest not in (portal.read_text(encoding="utf-8", errors="replace") if portal.is_file() else ""):
        errors.append(_error("entry_bundle_digest_missing", Path("submission/SUBMISSION_PORTAL_CHECKLIST.md"), f"portal checklist must mention bundle digest `{bundle_digest}`"))

    return {"release_tag": release_tag, "truth_status": release_truth, "bundle_digest": bundle_digest}


def _check_video_metadata(root: Path, errors: list[dict[str, Any]]) -> None:
    rel = Path("submission/VIDEO_METADATA.md")
    path = root / rel
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    normalized = text.replace("–", "-")
    if "1-3 minutes" not in normalized:
        errors.append(_error("entry_video_duration_requirement", rel, "video metadata must state hard 1-3 minute requirement"))
    if not re.search(r"2:20\s*-\s*2:45", normalized):
        errors.append(_error("entry_video_target_duration", rel, "video metadata must state target 2:20-2:45 duration"))
    if not re.search(r"\b(mp4|h\.264|h264)\b", normalized, re.IGNORECASE):
        errors.append(_error("entry_video_export_format", rel, "video metadata must include common MP4/H.264 export guidance"))


def _check_judge_qa_completion(root: Path, errors: list[dict[str, Any]]) -> None:
    rel = Path("submission/JUDGE_QA.md")
    path = root / rel
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8", errors="replace").lower()
    required = [
        "algora",
        "buyer side",
        "seller side",
        "stripe structural",
        "hermes structural",
        "nvidia/openshell structural",
        "legitimate first bounty",
        "viability beyond the demo",
        "moat",
        "production money",
    ]
    for phrase in required:
        if phrase not in text:
            errors.append(_error("judge_qa_missing_entry_answer", rel, f"judge Q&A must answer `{phrase}`"))


def _placeholder_locations(rel: Path, text: str) -> list[dict[str, Any]]:
    locations: list[dict[str, Any]] = []
    for match in ENTRY_PLACEHOLDER_RE.finditer(text):
        locations.append({"path": str(rel), "line": text.count("\n", 0, match.start()) + 1, "placeholder": match.group(0)})
    return locations


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _error(code: str, path: Path, detail: str, *, line: int | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "path": str(path), "detail": detail}
    if line is not None:
        error["line"] = line
    return error
