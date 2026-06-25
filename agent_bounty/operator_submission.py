from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .release_integrity import release_audit_report
from .submission_check import SECRET_PATTERNS
from .util import file_digest, sha256_bytes, stable_json


OPERATOR_STATE_SCHEMA = "agent-bounty-operator-submission-state-v1"
FINALIZER_SCHEMA = "agent-bounty-submission-finalizer-v1"
VIDEO_REPORT_SCHEMA = "agent-bounty-video-check-v1"
MANUAL_MEDIA_REPORT_SCHEMA = "agent-bounty-manual-media-report-v1"
X_COUNTER_SCHEMA = "agent-bounty-x-counter-v1"

DEFAULT_OPERATOR_STATE_PATH = Path(".demo/operator-submission.json")
DEFAULT_FINALIZER_OUTPUT = Path(".demo/final-submission")
OPERATOR_STATE_EXAMPLE_PATH = Path("submission/operator-submission.example.json")

X_POST_LIMIT = 280
X_ULTRA_SHORT_LIMIT = 180
X_TCO_URL_LENGTH = 23
X_TCO_URL_LENGTH_SOURCE = {
    "url": "https://docs.x.com/fundamentals/counting-characters",
    "retrieved_at": "2026-06-25",
    "rule": "All URLs are wrapped with t.co and count as 23 characters.",
}

REQUIRED_PREPOST_FIELDS = [
    "repo_url",
    "video_file_path",
    "video_filename",
    "team_name",
    "team_member_names",
    "contact_email_or_handle",
    "bundle_backup_path",
]
REQUIRED_FINAL_FIELDS = [
    "final_tweet_url",
    "discord_confirmation_path",
    "typeform_confirmation_path",
]

URL_RE = re.compile(r"https?://[^\s<>()`\"']+")
GITHUB_REPO_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?$")
X_URL_RE = re.compile(r"^https://(?:x\.com|twitter\.com)/[A-Za-z0-9_]{1,15}/status/[0-9]+(?:[/?#].*)?$")
PLACEHOLDER_RE = re.compile(r"\[[A-Z][A-Z0-9_ /.-]*\]|\b(?:TODO|TBD|TO_BE_FILLED)\b")
UNSAFE_PATH_NAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
    "known_hosts",
    "credentials",
    "credentials.json",
    "token",
    "tokens",
}


def x_character_count(text: str, *, url_length: int = X_TCO_URL_LENGTH) -> int:
    text = re.sub(r"\[(?:REPO_URL|FINAL_TWEET_URL|DEMO_URL_OPTIONAL)\]", "https://example.com", text)
    total = 0
    pos = 0
    for match in URL_RE.finditer(text):
        total += _conservative_text_weight(text[pos : match.start()])
        total += url_length
        pos = match.end()
    total += _conservative_text_weight(text[pos:])
    return total


def render_tweet_variants(root: Path, state: dict[str, Any], *, url_length: int = X_TCO_URL_LENGTH) -> list[dict[str, Any]]:
    from .submission_check import extract_tweet_variants

    tweet_path = root / "submission" / "TWEET.md"
    text = tweet_path.read_text(encoding="utf-8")
    repo_url = str(state.get("repo_url") or "").strip()
    variants: list[dict[str, Any]] = []
    for variant in extract_tweet_variants(text):
        body = variant["body"].replace("[REPO_URL]", repo_url)
        body = body.replace("[DEMO_URL_OPTIONAL]", "")
        body = re.sub(r"[ \t]+\n", "\n", body).strip()
        variants.append(
            {
                "name": variant["name"],
                "status": variant["status"],
                "body": body,
                "x_count": x_character_count(body, url_length=url_length),
                "limit": X_POST_LIMIT,
                "sha256": sha256_bytes(body.encode("utf-8")),
            }
        )
    return variants


def operator_state_report(
    state_path: Path,
    *,
    root: Path | None = None,
    mode: str = "prepost",
    manual_media_report: Path | None = None,
    ffprobe_path: str | None = None,
) -> dict[str, Any]:
    root_path = (root or Path.cwd()).resolve()
    state_result = _load_operator_state(state_path)
    errors: list[dict[str, Any]] = list(state_result["errors"])
    state = state_result["state"]
    mode = _normalize_mode(mode)

    if state:
        _validate_operator_state_fields(state, mode=mode, errors=errors)

    video_report: dict[str, Any] | None = None
    tweet_report: dict[str, Any] | None = None
    release_report: dict[str, Any] | None = None

    if state:
        video_path = Path(str(state.get("video_file_path") or ""))
        manual_path = manual_media_report or _optional_path(state.get("manual_media_report_path"))
        video_report = video_check_report(video_path, manual_report=manual_path, ffprobe_path=ffprobe_path)
        if not video_report.get("ok"):
            for error in video_report.get("errors", []):
                errors.append(_error("video_" + str(error.get("code", "check_failed")), str(state_path), str(error.get("detail", "video check failed"))))

        tweet_errors: list[dict[str, Any]] = []
        tweets = render_tweet_variants(root_path, state)
        for tweet in tweets:
            if tweet["x_count"] > X_POST_LIMIT:
                tweet_errors.append(_error("tweet_too_long", "submission/TWEET.md", f"{tweet['name']} is {tweet['x_count']} characters; limit is {X_POST_LIMIT}"))
            if "ultra" in tweet["name"].lower() and tweet["x_count"] > X_ULTRA_SHORT_LIMIT:
                tweet_errors.append(_error("tweet_ultra_short_too_long", "submission/TWEET.md", f"{tweet['name']} is {tweet['x_count']} characters; limit is {X_ULTRA_SHORT_LIMIT}"))
            if "@NousResearch" not in tweet["body"]:
                tweet_errors.append(_error("tweet_missing_nous_tag", "submission/TWEET.md", f"{tweet['name']} must include @NousResearch"))
            if "Mixed real/fallback" not in tweet["body"]:
                tweet_errors.append(_error("tweet_missing_truth_boundary", "submission/TWEET.md", f"{tweet['name']} must include Mixed real/fallback"))
        errors.extend(tweet_errors)
        tweet_report = {
            "schema": X_COUNTER_SCHEMA,
            "url_length": X_TCO_URL_LENGTH,
            "url_length_source": X_TCO_URL_LENGTH_SOURCE,
            "variants": [{k: v for k, v in tweet.items() if k != "body"} for tweet in tweets],
            "errors": tweet_errors,
        }

    if mode == "final":
        try:
            release_manifest = _read_json(root_path / "submission" / "RELEASE_MANIFEST.json")
            tag = str(release_manifest.get("release_tag") or "")
            release_report = release_audit_report(root_path, tag=tag) if tag else {"ok": False, "errors": [_error("release_tag_missing", "submission/RELEASE_MANIFEST.json", "release tag is required")]}
        except Exception as exc:  # pragma: no cover - defensive boundary
            release_report = {"ok": False, "errors": [_error("release_audit_failed", "submission/RELEASE_MANIFEST.json", str(exc))]}
        if not release_report.get("ok"):
            for error in release_report.get("errors", []):
                errors.append(_error("release_" + str(error.get("code", "audit_failed")), str(error.get("path", "release-audit")), str(error.get("detail", "release audit failed"))))

    return {
        "schema": "agent-bounty-operator-state-report-v1",
        "ok": not errors,
        "mode": mode,
        "state_path": _safe_display_path(state_path),
        "state_digest": file_digest(state_path) if state_path.is_file() else None,
        "resolved": _safe_state_summary(state),
        "video": _safe_video_summary(video_report) if video_report else None,
        "tweets": tweet_report,
        "release": _safe_release_summary(release_report) if release_report else None,
        "errors": errors,
    }


def video_check_report(
    file_path: Path,
    *,
    manual_report: Path | None = None,
    ffprobe_path: str | None = None,
    require_audio: bool = True,
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    path = file_path.expanduser()
    summary: dict[str, Any] = {
        "schema": VIDEO_REPORT_SCHEMA,
        "file_name": path.name,
        "exists": path.is_file(),
        "readable": False,
        "size_bytes": 0,
        "sha256": None,
        "ffprobe_available": False,
        "manual_report": None,
        "metadata": {},
        "errors": errors,
    }
    if not path.is_file():
        errors.append(_error("missing_file", path.name or "video", "video file does not exist or is not a regular file"))
        summary["ok"] = False
        return summary
    try:
        size = path.stat().st_size
        summary["size_bytes"] = size
        summary["readable"] = os.access(path, os.R_OK)
        summary["sha256"] = file_digest(path)
    except OSError as exc:
        errors.append(_error("unreadable_file", path.name, str(exc)))
        summary["ok"] = False
        return summary
    if summary["size_bytes"] <= 0:
        errors.append(_error("empty_file", path.name, "video file is empty"))

    ffprobe = ffprobe_path if ffprobe_path is not None else shutil.which("ffprobe")
    if ffprobe:
        summary["ffprobe_available"] = True
        metadata, probe_errors = _ffprobe_metadata(path, ffprobe)
        errors.extend(probe_errors)
        summary["metadata"] = metadata
    elif manual_report:
        manual = _load_manual_media_report(manual_report)
        summary["manual_report"] = _safe_manual_report_summary(manual_report, manual)
        errors.extend(manual["errors"])
        summary["metadata"] = manual["metadata"]
    else:
        errors.append(_error("ffprobe_missing", "ffprobe", "ffprobe is not available; provide a manually attested media report"))

    if summary.get("metadata"):
        _validate_media_metadata(summary["metadata"], errors, require_audio=require_audio)
    summary["ok"] = not errors
    return summary


def finalize_submission(
    *,
    state_path: Path,
    output_dir: Path,
    root: Path | None = None,
    check: bool = False,
    manual_media_report: Path | None = None,
    ffprobe_path: str | None = None,
) -> dict[str, Any]:
    root_path = (root or Path.cwd()).resolve()
    report = operator_state_report(
        state_path,
        root=root_path,
        mode="prepost",
        manual_media_report=manual_media_report,
        ffprobe_path=ffprobe_path,
    )
    state = _load_operator_state(state_path)["state"]
    recording = recording_acceptance_report(root_path)
    errors = list(report.get("errors", []))
    if not recording.get("ok"):
        errors.extend(recording.get("errors", []))
    files: dict[str, str] = {}
    if report.get("ok") and recording.get("ok"):
        rendered = _render_final_files(root_path, state, report)
        for name, content in rendered.items():
            files[name] = sha256_bytes(content.encode("utf-8"))
        if not check:
            output = output_dir.resolve()
            output.mkdir(parents=True, exist_ok=True)
            for name, content in rendered.items():
                (output / name).write_text(content, encoding="utf-8")

    return {
        "schema": FINALIZER_SCHEMA,
        "ok": bool(report.get("ok") and recording.get("ok")),
        "mode": "check" if check else "write",
        "state_path": _safe_display_path(state_path),
        "output_dir": _safe_display_path(output_dir),
        "would_write": sorted(files),
        "file_digests": files,
        "operator": report,
        "recording": recording,
        "errors": errors,
    }


def recording_acceptance_report(root: Path | None = None) -> dict[str, Any]:
    root_path = (root or Path.cwd()).resolve()
    errors: list[dict[str, Any]] = []
    release = _read_json(root_path / "submission" / "RELEASE_MANIFEST.json")
    bundle_manifest = _read_json(root_path / "demo" / "bundles" / "winning-run" / "manifest.json")
    cues = _read_json(root_path / "demo" / "bundles" / "winning-run" / "director-cues.json")
    release_tag = str(release.get("release_tag") or "")
    bundle_digest = str(bundle_manifest.get("bundle_digest") or "")
    if release.get("bundle_digest") != bundle_digest:
        errors.append(_error("recording_bundle_digest_mismatch", "submission/RELEASE_MANIFEST.json", "release manifest bundle digest must match director bundle"))
    scenes = cues.get("scenes") if isinstance(cues.get("scenes"), list) else []
    if len(scenes) != 7:
        errors.append(_error("recording_scene_count", "demo/bundles/winning-run/director-cues.json", "director must expose seven scenes"))
    if cues.get("truth_badge") != "Mixed real/fallback":
        errors.append(_error("recording_truth_badge", "demo/bundles/winning-run/director-cues.json", "director truth badge must be Mixed real/fallback"))
    for rel in ["submission/VOICEOVER_FINAL.md", "submission/RECORDING_RUNBOOK.md"]:
        path = root_path / rel
        if not path.is_file():
            errors.append(_error("recording_doc_missing", rel, "recording document is missing"))
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if release_tag and release_tag not in text:
            errors.append(_error("recording_release_tag_missing", rel, f"recording document must mention {release_tag}"))
        if "Mixed real/fallback" not in text:
            errors.append(_error("recording_truth_missing", rel, "recording document must mention Mixed real/fallback"))
    return {
        "schema": "agent-bounty-recording-acceptance-v1",
        "ok": not errors,
        "release_tag": release_tag,
        "bundle_digest": bundle_digest,
        "scene_count": len(scenes),
        "truth_badge": cues.get("truth_badge"),
        "record_url": "http://127.0.0.1:8788/director-record.html?duration=120&autoplay=1",
        "errors": errors,
    }


def _conservative_text_weight(text: str) -> int:
    total = 0
    for char in text:
        code = ord(char)
        if code <= 0x10FF:
            total += 1
        else:
            total += 2
    return total


def _normalize_mode(mode: str) -> str:
    clean = mode.strip().lower()
    if clean not in {"prepost", "final"}:
        raise ValueError("mode must be prepost or final")
    return clean


def _load_operator_state(path: Path) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    if not path.is_file():
        errors.append(_error("operator_state_missing", _safe_display_path(path), "operator state file is required"))
        return {"state": state, "errors": errors}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(_error("operator_state_invalid_json", _safe_display_path(path), str(exc)))
        return {"state": state, "errors": errors}
    if not isinstance(parsed, dict):
        errors.append(_error("operator_state_schema", _safe_display_path(path), "operator state must be a JSON object"))
        return {"state": state, "errors": errors}
    state = parsed
    if state.get("schema") != OPERATOR_STATE_SCHEMA:
        errors.append(_error("operator_state_schema", _safe_display_path(path), f"schema must be {OPERATOR_STATE_SCHEMA}"))
    return {"state": state, "errors": errors}


def _validate_operator_state_fields(state: dict[str, Any], *, mode: str, errors: list[dict[str, Any]]) -> None:
    required = REQUIRED_PREPOST_FIELDS + (REQUIRED_FINAL_FIELDS if mode == "final" else [])
    for field in required:
        if not _present(state.get(field)):
            errors.append(_error("operator_field_missing", field, f"{field} is required in {mode} mode"))

    for field, value in state.items():
        if isinstance(value, str):
            _validate_no_secret_text(field, value, errors)
            if PLACEHOLDER_RE.search(value):
                errors.append(_error("operator_placeholder", field, f"{field} still contains placeholder text"))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if not isinstance(item, str) or not item.strip():
                    errors.append(_error("operator_field_invalid", field, f"{field}[{index}] must be a non-empty string"))
                else:
                    _validate_no_secret_text(f"{field}[{index}]", item, errors)
        elif value is not None:
            errors.append(_error("operator_field_invalid", field, f"{field} must be a string, list of strings, or null"))

    repo_url = str(state.get("repo_url") or "").strip()
    if repo_url and not GITHUB_REPO_RE.match(repo_url):
        errors.append(_error("operator_repo_url_invalid", "repo_url", "repo_url must be a canonical https://github.com/owner/repo URL"))
    tweet_url = str(state.get("final_tweet_url") or "").strip()
    if tweet_url and not X_URL_RE.match(tweet_url):
        errors.append(_error("operator_tweet_url_invalid", "final_tweet_url", "final_tweet_url must be an X/Twitter status URL"))

    for field in ["video_file_path", "bundle_backup_path", "discord_confirmation_path", "typeform_confirmation_path", "manual_media_report_path"]:
        value = str(state.get(field) or "").strip()
        if value:
            _validate_safe_local_path(field, value, errors)

    team_members = state.get("team_member_names")
    if isinstance(team_members, str):
        errors.append(_error("operator_field_invalid", "team_member_names", "team_member_names must be a list of strings"))


def _validate_no_secret_text(field: str, value: str, errors: list[dict[str, Any]]) -> None:
    for pattern in SECRET_PATTERNS:
        if pattern.search(value):
            errors.append(_error("operator_secret_like_value", field, f"{field} contains a secret-like value"))
            return


def _validate_safe_local_path(field: str, value: str, errors: list[dict[str, Any]]) -> None:
    if "\x00" in value:
        errors.append(_error("operator_path_invalid", field, f"{field} contains a NUL byte"))
        return
    path = Path(value)
    lower_parts = {part.lower() for part in path.parts}
    if lower_parts & UNSAFE_PATH_NAMES:
        errors.append(_error("operator_path_sensitive", field, f"{field} points at a credential-like path"))
    if any(part == ".." for part in path.parts):
        errors.append(_error("operator_path_escape", field, f"{field} must not contain .. path segments"))


def _ffprobe_metadata(path: Path, ffprobe: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "ffprobe failed").strip()
        return {}, [_error("ffprobe_failed", path.name, detail)]
    try:
        raw = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {}, [_error("ffprobe_invalid_json", path.name, str(exc))]
    return _metadata_from_ffprobe(raw), []


def _metadata_from_ffprobe(raw: dict[str, Any]) -> dict[str, Any]:
    streams = raw.get("streams") if isinstance(raw.get("streams"), list) else []
    fmt = raw.get("format") if isinstance(raw.get("format"), dict) else {}
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    return {
        "source": "ffprobe",
        "duration_seconds": _float_or_none(fmt.get("duration") or video.get("duration")),
        "container": str(fmt.get("format_name") or ""),
        "video_codec": str(video.get("codec_name") or ""),
        "audio_codec": str(audio.get("codec_name") or ""),
        "width": _int_or_none(video.get("width")),
        "height": _int_or_none(video.get("height")),
        "frame_rate": _parse_rate(str(video.get("avg_frame_rate") or video.get("r_frame_rate") or "")),
        "audio_stream_present": bool(audio),
    }


def _load_manual_media_report(path: Path) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
    if not path.is_file():
        return {"metadata": metadata, "errors": [_error("manual_report_missing", _safe_display_path(path), "manual media report does not exist")]}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"metadata": metadata, "errors": [_error("manual_report_invalid_json", _safe_display_path(path), str(exc))]}
    if not isinstance(raw, dict) or raw.get("schema") != MANUAL_MEDIA_REPORT_SCHEMA:
        errors.append(_error("manual_report_schema", _safe_display_path(path), f"schema must be {MANUAL_MEDIA_REPORT_SCHEMA}"))
    metadata = {
        "source": "manual-attestation",
        "duration_seconds": _float_or_none(raw.get("duration_seconds")),
        "container": str(raw.get("container") or ""),
        "video_codec": str(raw.get("video_codec") or ""),
        "audio_codec": str(raw.get("audio_codec") or ""),
        "width": _int_or_none(raw.get("width")),
        "height": _int_or_none(raw.get("height")),
        "frame_rate": _float_or_none(raw.get("frame_rate")),
        "audio_stream_present": bool(raw.get("audio_stream_present")),
        "attested_by": bool(raw.get("attested_by")),
        "created_at": bool(raw.get("created_at")),
    }
    if not raw.get("attested_by"):
        errors.append(_error("manual_report_attester_missing", _safe_display_path(path), "manual report requires attested_by"))
    if not raw.get("created_at"):
        errors.append(_error("manual_report_timestamp_missing", _safe_display_path(path), "manual report requires created_at"))
    return {"metadata": metadata, "errors": errors}


def _validate_media_metadata(metadata: dict[str, Any], errors: list[dict[str, Any]], *, require_audio: bool) -> None:
    duration = metadata.get("duration_seconds")
    if not isinstance(duration, (int, float)):
        errors.append(_error("duration_missing", "video", "duration_seconds is required"))
    else:
        if duration < 60:
            errors.append(_error("duration_too_short", "video", "duration must be at least 60 seconds"))
        if duration > 180:
            errors.append(_error("duration_too_long", "video", "duration must be no more than 180 seconds"))
    container = str(metadata.get("container") or "").lower()
    if container and not any(token in container for token in ["mp4", "mov", "m4v", "quicktime"]):
        errors.append(_error("container_incompatible", "video", "container should be MP4/QuickTime-compatible"))
    video_codec = str(metadata.get("video_codec") or "").lower()
    if video_codec and video_codec not in {"h264", "avc1", "hevc", "h265"}:
        errors.append(_error("video_codec_incompatible", "video", "video codec should be H.264/H.265-compatible"))
    if not metadata.get("width") or not metadata.get("height"):
        errors.append(_error("resolution_missing", "video", "resolution is required"))
    if require_audio and not metadata.get("audio_stream_present"):
        errors.append(_error("audio_missing", "video", "audio stream is required"))


def _render_final_files(root: Path, state: dict[str, Any], report: dict[str, Any]) -> dict[str, str]:
    values = _placeholder_values(state)
    tweets = render_tweet_variants(root, state)
    tweet_body = "# Final Tweet Copy\n\n"
    for tweet in tweets:
        tweet_body += f"## {tweet['name']}\n\n"
        tweet_body += f"X character count: {tweet['x_count']} / {tweet['limit']}\n\n"
        tweet_body += "```text\n" + tweet["body"] + "\n```\n\n"
    tweet_body += "Counting rule: URLs count as 23 characters through X/t.co; see MEDIA_REPORT.json for the local validation report.\n"

    discord = _replace_template(root / "submission" / "DISCORD_SUBMISSION.md", values)
    typeform = _replace_template(root / "submission" / "TYPEFORM_FINAL.md", values)
    portal = _replace_template(root / "submission" / "SUBMISSION_PORTAL_CHECKLIST.md", values)
    final_report = {
        "schema": "agent-bounty-final-entry-report-v1",
        "generated_at": state.get("submission_timestamp") or "not-recorded",
        "state_digest": report.get("state_digest"),
        "operator": report,
        "recording": recording_acceptance_report(root),
    }
    return {
        "FINAL_TWEET.md": tweet_body,
        "FINAL_DISCORD.md": discord,
        "FINAL_TYPEFORM.md": typeform,
        "FINAL_PORTAL_CHECKLIST.md": portal,
        "MEDIA_REPORT.json": stable_json(report.get("video") or {}) + "\n",
        "FINAL_ENTRY_REPORT.json": stable_json(final_report) + "\n",
    }


def _replace_template(path: Path, values: dict[str, str]) -> str:
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace(f"[{key}]", value)
    return text


def _placeholder_values(state: dict[str, Any]) -> dict[str, str]:
    team_members = state.get("team_member_names")
    if isinstance(team_members, list):
        team_member_text = ", ".join(str(item).strip() for item in team_members if str(item).strip())
    else:
        team_member_text = str(team_members or "")
    video_path = str(state.get("video_file_path") or "")
    return {
        "REPO_URL": str(state.get("repo_url") or ""),
        "FINAL_TWEET_URL": str(state.get("final_tweet_url") or ""),
        "TEAM_NAME": str(state.get("team_name") or ""),
        "TEAM_MEMBER_NAMES": team_member_text,
        "CONTACT_EMAIL_OR_HANDLE": str(state.get("contact_email_or_handle") or ""),
        "FINAL_VIDEO_FILE_PATH": video_path,
        "FINAL_VIDEO_FILENAME": str(state.get("video_filename") or Path(video_path).name),
        "DISCORD_CONFIRMATION_PATH": str(state.get("discord_confirmation_path") or ""),
        "TYPEFORM_CONFIRMATION_PATH": str(state.get("typeform_confirmation_path") or ""),
        "BUNDLE_BACKUP_PATH": str(state.get("bundle_backup_path") or ""),
        "LOCAL_REPO_PATH": str(Path.cwd()),
        "DEMO_URL_OPTIONAL": "",
    }


def _present(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value) and all(isinstance(item, str) and item.strip() for item in value)
    return False


def _optional_path(value: Any) -> Path | None:
    if isinstance(value, str) and value.strip():
        return Path(value.strip())
    return None


def _safe_state_summary(state: dict[str, Any]) -> dict[str, Any]:
    if not state:
        return {}
    return {
        "schema": state.get("schema"),
        "repo_url_present": _present(state.get("repo_url")),
        "video_file_name": Path(str(state.get("video_file_path") or state.get("video_filename") or "")).name,
        "team_name_present": _present(state.get("team_name")),
        "team_member_count": len(state.get("team_member_names") or []) if isinstance(state.get("team_member_names"), list) else 0,
        "contact_present": _present(state.get("contact_email_or_handle")),
        "final_tweet_url_present": _present(state.get("final_tweet_url")),
        "discord_confirmation_present": _present(state.get("discord_confirmation_path")),
        "typeform_confirmation_present": _present(state.get("typeform_confirmation_path")),
        "bundle_backup_present": _present(state.get("bundle_backup_path")),
        "manual_media_report_present": _present(state.get("manual_media_report_path")),
        "submission_timestamp_present": _present(state.get("submission_timestamp")),
    }


def _safe_video_summary(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "schema": report.get("schema"),
        "ok": report.get("ok"),
        "file_name": report.get("file_name"),
        "exists": report.get("exists"),
        "readable": report.get("readable"),
        "size_bytes": report.get("size_bytes"),
        "sha256": report.get("sha256"),
        "ffprobe_available": report.get("ffprobe_available"),
        "manual_report": report.get("manual_report"),
        "metadata": report.get("metadata"),
        "errors": report.get("errors"),
    }


def _safe_manual_report_summary(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": _safe_display_path(path),
        "digest": file_digest(path) if path.is_file() else None,
        "metadata_source": report.get("metadata", {}).get("source"),
    }


def _safe_release_summary(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "ok": report.get("ok"),
        "release_tag": report.get("release_tag"),
        "bundle_digest": report.get("bundle_digest"),
        "attestation_digest": report.get("attestation_digest"),
        "truth_matrix_digest": report.get("truth_matrix_digest"),
        "tag_audit": report.get("tag_audit"),
        "errors": report.get("errors"),
    }


def _safe_display_path(path: Path) -> str:
    raw = str(path)
    if raw.startswith(".demo/") or raw == ".demo":
        return raw
    return Path(raw).name


def _read_json(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_rate(value: str) -> float | None:
    if not value or value == "0/0":
        return None
    if "/" in value:
        left, right = value.split("/", 1)
        numerator = _float_or_none(left)
        denominator = _float_or_none(right)
        if numerator is None or not denominator:
            return None
        return numerator / denominator
    return _float_or_none(value)


def _error(code: str, path: str, detail: str) -> dict[str, Any]:
    return {"code": code, "path": path, "detail": detail}
