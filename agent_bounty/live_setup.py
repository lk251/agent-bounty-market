from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .github_integration import github_status_report
from .hermes_integration import MIN_HERMES_CONTEXT_TOKENS, hermes_status_report
from .nvidia_runtime import nvidia_runtime_status_report
from .stripe_sandbox import OfficialStripeClient, PINNED_STRIPE_PACKAGE, StripeSandboxConfig, safe_error_message, stripe_cli_version, stripe_package_version
from .util import stable_json, utc_now


LIVE_SETUP_SCHEMA = "agent-bounty-live-setup-wizard-v1"
LIVE_SETUP_RUNBOOK_SCHEMA = "agent-bounty-live-setup-runbook-v1"

SENSITIVE_ENV_NAMES = (
    "NVIDIA_API_KEY",
    "AGENT_BOUNTY_GITHUB_TOKEN",
    "GH_TOKEN",
    "AGENT_BOUNTY_GITHUB_WEBHOOK_SECRET",
    "STRIPE_TEST_SECRET_KEY",
    "STRIPE_TEST_WEBHOOK_SECRET",
)
SECRET_VALUE_RE = re.compile(
    r"(sk_test_|rk_test_|sk_live_|rk_live_|whsec_|ghp_|github_pat_|nvapi-)[A-Za-z0-9_\\-]+"
)


def live_setup_wizard_report() -> dict[str, Any]:
    hermes = hermes_status_report(probe_doctor=False, discover_models=False)
    nvidia = nvidia_runtime_status_report(discover_models=False, doctor=False)
    github = github_status_report()
    stripe = stripe_setup_status_report()

    components = [
        _hermes_component(hermes),
        _nvidia_component(nvidia),
        _github_component(github),
        _stripe_component(stripe),
    ]
    blockers = live_setup_blockers(components=components)
    report = {
        "schema": LIVE_SETUP_SCHEMA,
        "ok": not blockers,
        "created_at": utc_now(),
        "components": components,
        "blockers": blockers,
        "preflight_blockers": blockers,
        "next_commands": [command for component in components for command in component["next_commands"] if component["ready"]],
        "runbook_command": "python -m agent_bounty live-setup-wizard --write-runbook submission/LIVE_SETUP_RUNBOOK.md",
    }
    return _redact(report)


def live_setup_blockers(*, components: list[dict[str, Any]] | None = None, report: dict[str, Any] | None = None) -> list[str]:
    if report is not None:
        components = list(report.get("components") or [])
    components = components or []
    blockers: list[str] = []
    for component in components:
        component_id = component.get("id", "unknown")
        for blocker in component.get("blockers", []):
            blockers.append(f"{component_id}: {blocker}")
    return blockers


def stripe_setup_status_report() -> dict[str, Any]:
    config = StripeSandboxConfig.from_env()
    blockers: list[str] = []
    if not config.enabled:
        blockers.append("set AGENT_BOUNTY_STRIPE_SANDBOX=1")
    if not config.secret_key:
        blockers.append("set STRIPE_TEST_SECRET_KEY")
    elif not (config.secret_key.startswith("sk_test_") or config.secret_key.startswith("rk_test_")):
        blockers.append("replace non-test Stripe API key with sk_test_ or rk_test_")
    if not config.webhook_secret:
        blockers.append("set STRIPE_TEST_WEBHOOK_SECRET from stripe listen")
    elif not config.webhook_secret.startswith("whsec_"):
        blockers.append("set STRIPE_TEST_WEBHOOK_SECRET to the whsec_ value from stripe listen")
    if not config.connected_account_id:
        blockers.append("set STRIPE_TEST_CONNECTED_ACCOUNT_ID to a test connected account")
    package_version = stripe_package_version()
    if package_version != PINNED_STRIPE_PACKAGE:
        blockers.append(f"install optional Stripe package stripe=={PINNED_STRIPE_PACKAGE}")
    cli_version = stripe_cli_version()
    if cli_version is None:
        blockers.append("install/authenticate Stripe CLI")

    platform: dict[str, Any] | None = None
    connected: dict[str, Any] | None = None
    if config.enabled and config.secret_key and package_version == PINNED_STRIPE_PACKAGE:
        try:
            client = OfficialStripeClient(config)
            account = client.retrieve_account(None)
            platform = {
                "id": account.get("id"),
                "country": account.get("country"),
                "livemode": account.get("livemode"),
            }
            if config.platform_account_id and platform["id"] != config.platform_account_id:
                blockers.append("authenticated platform account does not match STRIPE_TEST_PLATFORM_ACCOUNT_ID")
            if config.connected_account_id:
                connected_account = client.retrieve_account(config.connected_account_id)
                connected = {
                    "id": connected_account.get("id"),
                    "country": connected_account.get("country"),
                    "livemode": connected_account.get("livemode"),
                    "charges_enabled": bool(connected_account.get("charges_enabled", False)),
                    "payouts_enabled": bool(connected_account.get("payouts_enabled", False)),
                }
        except Exception as exc:
            blockers.append(f"Stripe authenticated status failed: {safe_error_message(exc)}")
    return _redact(
        {
            "schema": "agent-bounty-stripe-setup-status-v1",
            "ok": not blockers,
            "sandbox_enabled": config.enabled,
            "stripe_package_version": package_version,
            "stripe_package_required": f"stripe=={PINNED_STRIPE_PACKAGE}",
            "stripe_cli": cli_version,
            "secret_key_configured": bool(config.secret_key),
            "webhook_secret_configured": bool(config.webhook_secret),
            "connected_account_configured": bool(config.connected_account_id),
            "platform_account": platform,
            "connected_account": connected or ({"id": config.connected_account_id} if config.connected_account_id else None),
            "public_base_url": config.public_base_url,
            "blockers": blockers,
        }
    )


def render_live_setup_text(report: dict[str, Any]) -> str:
    lines = ["Agent Bounty Live Setup Wizard", f"status: {'ready' if report.get('ok') else 'blocked'}", ""]
    for component in report.get("components", []):
        lines.append(f"{component['label']}: {'ready' if component['ready'] else 'blocked'}")
        for check in component.get("checks", []):
            status = "ok" if check.get("ok") else "missing"
            detail = f" - {check['detail']}" if check.get("detail") else ""
            lines.append(f"  [{status}] {check['label']}{detail}")
        if component.get("blockers"):
            lines.append("  blockers:")
            for blocker in component["blockers"]:
                lines.append(f"  - {blocker}")
        if component.get("next_commands"):
            lines.append("  next:")
            for command in component["next_commands"]:
                lines.append(f"  - {command}")
        if component.get("ready_commands") and not component.get("ready"):
            lines.append("  when ready:")
            for command in component["ready_commands"]:
                lines.append(f"  - {command}")
        lines.append("")
    lines.append("Runbook:")
    lines.append(str(report.get("runbook_command")))
    return _redact_text("\n".join(lines).rstrip() + "\n")


def write_live_setup_runbook(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render_live_setup_runbook(report)
    path.write_text(text, encoding="utf-8")
    return {
        "schema": LIVE_SETUP_RUNBOOK_SCHEMA,
        "ok": True,
        "path": str(path),
        "bytes": len(text.encode("utf-8")),
    }


def render_live_setup_runbook(report: dict[str, Any]) -> str:
    lines = [
        "# Live Setup Runbook",
        "",
        "This runbook uses placeholders only. Do not commit real API keys, webhook",
        "secrets, checkout URLs, or raw webhook payloads.",
        "",
        "## Environment Placeholders",
        "",
        "```bash",
        "export NVIDIA_API_KEY=...",
        "export AGENT_BOUNTY_NVIDIA_MODEL_ID=...",
        "export AGENT_BOUNTY_RUN_HERMES_PROJECT_AGENT=1",
        "export AGENT_BOUNTY_HERMES_PROJECT_EVALUATE_COMMAND='...reviewed project wrapper...'",
        "export AGENT_BOUNTY_HERMES_SOLVER_EVALUATE_COMMAND='...reviewed solver wrapper...'",
        "export AGENT_BOUNTY_HERMES_CONTEXT_TOKENS=65536",
        "export AGENT_BOUNTY_GITHUB_INTEGRATION=1",
        "export AGENT_BOUNTY_GITHUB_TOKEN=...",
        "export GH_TOKEN=...",
        "export AGENT_BOUNTY_GITHUB_REPOSITORY=owner/repo",
        "export AGENT_BOUNTY_GITHUB_WEBHOOK_SECRET=...",
        "export AGENT_BOUNTY_STRIPE_SANDBOX=1",
        "export STRIPE_TEST_SECRET_KEY=sk_test_...",
        "export STRIPE_TEST_WEBHOOK_SECRET=whsec_...",
        "export STRIPE_TEST_CONNECTED_ACCOUNT_ID=acct_...",
        "export STRIPE_TEST_PLATFORM_ACCOUNT_ID=acct_...",
        "export AGENT_BOUNTY_PUBLIC_BASE_URL=http://127.0.0.1:4242",
        "```",
        "",
        "## Checklist",
        "",
    ]
    for component in report.get("components", []):
        lines.extend([f"### {component['label']}", ""])
        for blocker in component.get("blockers", []):
            lines.append(f"- [ ] {blocker}")
        if not component.get("blockers"):
            lines.append("- [x] Ready for the next narrow command.")
        lines.append("")
        lines.append("Commands:")
        lines.append("")
        lines.append("```bash")
        commands = component.get("setup_commands", []) + component.get("ready_commands", [])
        for command in dict.fromkeys(commands):
            lines.append(command)
        lines.append("```")
        lines.append("")
    lines.extend(
        [
            "## Verify",
            "",
            "```bash",
            "python -m agent_bounty live-setup-wizard --format json",
            "python -m agent_bounty demo-preflight --mode live",
            "```",
            "",
        ]
    )
    return _redact_text("\n".join(lines))


def _hermes_component(status: dict[str, Any]) -> dict[str, Any]:
    hermes = status.get("hermes") or {}
    provider = status.get("provider") or {}
    wrappers = status.get("wrappers") or {}
    skills = status.get("skills") or {}
    skills_current = _skills_manifest_current(skills)
    checks = [
        _check("hermes_cli", "Hermes executable/version", bool(hermes.get("path") and (hermes.get("version") or {}).get("ok")), _version_excerpt(hermes.get("version"))),
        _check("skills", "Skill manifest installed and current", skills_current, skills.get("manifest_digest")),
        _check("nvidia_api_key", "NVIDIA_API_KEY configured", bool(provider.get("nvidia_api_key_present"))),
        _check("model_id", "NVIDIA model ID configured", bool(provider.get("model_id") and provider.get("model_id") != "not-configured"), provider.get("model_id")),
        _check(
            "context",
            f"Hermes context >= {MIN_HERMES_CONTEXT_TOKENS}",
            bool((provider.get("context_tokens") or 0) >= MIN_HERMES_CONTEXT_TOKENS),
            provider.get("context_tokens"),
        ),
        _check("project_wrapper", "Project wrapper configured", bool(wrappers.get("project_command_configured"))),
        _check("solver_wrapper", "Solver wrapper configured", bool(wrappers.get("solver_command_configured"))),
    ]
    blockers = _missing_checks(checks) + list(status.get("blockers") or [])
    return _component(
        "hermes_nvidia",
        "Hermes/NVIDIA",
        checks,
        blockers,
        setup_commands=[
            "python -m agent_bounty hermes-install-skills",
            "python -m agent_bounty hermes-status --discover-models",
        ],
        next_commands=["python -m agent_bounty demo-hermes-decisions --db .demo/hermes-live.sqlite3 --require-real"],
    )


def _nvidia_component(status: dict[str, Any]) -> dict[str, Any]:
    docker = status.get("docker") or {}
    openshell_cli = status.get("openshell_cli") or {}
    nemoclaw = status.get("nemoclaw") or {}
    policy = status.get("policy") or {}
    checks = [
        _check("docker", "Docker available", bool(docker.get("available")), docker.get("path") or docker.get("blocker")),
        _check("openshell", "OpenShell available", bool(openshell_cli.get("path") and status.get("openshell", {}).get("available")), openshell_cli.get("version") or openshell_cli.get("blocker")),
        _check("nemoclaw", "NemoClaw/community artifacts", bool(nemoclaw.get("available") or nemoclaw.get("path")), nemoclaw.get("version") or nemoclaw.get("blocker")),
        _check("policy", "Policy and manifest digests", bool(policy.get("policy_digest") and policy.get("manifest_digest")), policy.get("effective_policy_digest")),
    ]
    blockers = _missing_checks(checks) + list(status.get("blockers") or [])
    return _component(
        "openshell_nemoclaw",
        "OpenShell/NemoClaw",
        checks,
        blockers,
        setup_commands=[
            "python -m agent_bounty nvidia-runtime-status",
            "python -m agent_bounty nvidia-runtime-status --discover-models",
        ],
        next_commands=["python -m agent_bounty demo-nvidia-sandbox --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency --require-real"],
    )


def _github_component(status: dict[str, Any]) -> dict[str, Any]:
    checks = [
        _check("gh_cli", "gh CLI available/auth status", bool(status.get("gh_cli")), status.get("gh_cli")),
        _check("integration", "GitHub integration enabled", bool(status.get("enabled"))),
        _check("repository", "Repository configured/retrievable", bool(status.get("repository_configured") and (status.get("repository") or status.get("development_transport"))), (status.get("repository") or {}).get("full_name")),
        _check("webhook", "Webhook secret configured", bool(status.get("webhook_secret_configured"))),
        _check("capabilities", "Required capabilities declared", bool(status.get("required_capabilities")), ", ".join(status.get("required_capabilities") or [])),
    ]
    blockers = _missing_checks(checks) + list(status.get("blockers") or [])
    return _component(
        "github",
        "GitHub",
        checks,
        blockers,
        setup_commands=[
            "python -m agent_bounty github-status",
            "python -m agent_bounty github-webhook-serve --db .demo/github-live.sqlite3 --host 127.0.0.1 --port 4343",
        ],
        next_commands=["python -m agent_bounty demo-github-motoko-live --db .demo/github-live.sqlite3 --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency"],
    )


def _stripe_component(status: dict[str, Any]) -> dict[str, Any]:
    checks = [
        _check("package", "Stripe package installed", status.get("stripe_package_version") == PINNED_STRIPE_PACKAGE, status.get("stripe_package_version")),
        _check("cli", "Stripe CLI available", bool(status.get("stripe_cli")), status.get("stripe_cli")),
        _check("sandbox", "Sandbox flag enabled", bool(status.get("sandbox_enabled"))),
        _check("secret_key", "Test secret key configured", bool(status.get("secret_key_configured"))),
        _check("webhook", "Webhook secret configured", bool(status.get("webhook_secret_configured"))),
        _check("connected", "Connected account configured", bool(status.get("connected_account_configured")), (status.get("connected_account") or {}).get("id")),
        _check("accounts", "Platform/connected account safe retrieval", bool(status.get("platform_account") and status.get("connected_account")), (status.get("platform_account") or {}).get("id")),
    ]
    blockers = _missing_checks(checks) + list(status.get("blockers") or [])
    return _component(
        "stripe",
        "Stripe",
        checks,
        blockers,
        setup_commands=[
            "stripe listen --events payment_intent.succeeded,payment_intent.payment_failed,checkout.session.completed,checkout.session.expired,transfer.created,transfer.reversed --forward-to http://127.0.0.1:4242/stripe/webhook",
            "python -m agent_bounty stripe-webhook-serve --db .demo/stripe.sqlite3 --host 127.0.0.1 --port 4242",
            "python -m agent_bounty stripe-status",
        ],
        next_commands=[
            "python -m agent_bounty stripe-create-checkout --db .demo/stripe.sqlite3 --project-id project_motoko --source owner --amount-cents 2500 --currency usd --success-url http://127.0.0.1:4242/success --cancel-url http://127.0.0.1:4242/cancel",
            "python -m agent_bounty stripe-process-events --db .demo/stripe.sqlite3",
            "python -m agent_bounty demo-economic-loop-live --db .demo/stripe.sqlite3 --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency",
            "python -m agent_bounty stripe-reconcile --db .demo/stripe.sqlite3 --remote",
        ],
    )


def _component(
    component_id: str,
    label: str,
    checks: list[dict[str, Any]],
    blockers: list[str],
    *,
    setup_commands: list[str],
    next_commands: list[str],
) -> dict[str, Any]:
    deduped_blockers = list(dict.fromkeys(blocker for blocker in blockers if blocker))
    return {
        "id": component_id,
        "label": label,
        "ready": not deduped_blockers,
        "checks": checks,
        "blockers": deduped_blockers,
        "setup_commands": setup_commands,
        "ready_commands": next_commands,
        "next_commands": next_commands if not deduped_blockers else setup_commands,
    }


def _check(check_id: str, label: str, ok: bool, detail: Any = None) -> dict[str, Any]:
    return {"id": check_id, "label": label, "ok": bool(ok), "detail": detail}


def _missing_checks(checks: list[dict[str, Any]]) -> list[str]:
    return [f"{check['label']} is not ready" for check in checks if not check.get("ok")]


def _version_excerpt(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    text = value.get("stdout_excerpt") or value.get("stderr_excerpt") or value.get("error")
    if text is None:
        return None
    return str(text).splitlines()[0][:240]


def _skills_manifest_current(manifest: dict[str, Any]) -> bool:
    if not manifest.get("manifest_digest") or not manifest.get("hermes_skill_root"):
        return False
    path = Path(str(manifest["hermes_skill_root"])) / "agent-bounty-market-manifest.json"
    if not path.exists():
        return False
    try:
        installed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return installed.get("manifest_digest") == manifest.get("manifest_digest")


def _redact(value: Any) -> Any:
    return json.loads(_redact_text(stable_json(value)))


def _redact_text(text: str) -> str:
    redacted = text
    for name in SENSITIVE_ENV_NAMES:
        secret = os.environ.get(name)
        if secret:
            redacted = redacted.replace(secret, f"{name}=...")
    return SECRET_VALUE_RE.sub(lambda match: match.group(1) + "...", redacted)
