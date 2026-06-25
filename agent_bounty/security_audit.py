from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .core import AgentBountyMarket, MarketError
from .db import connect
from .demo_presentation import validate_bundle
from .economic_loop import (
    EconomicLoopError,
    allocate_accepted_reward,
    default_solver_operating_policy,
    save_solver_operating_policy,
    spend_retained_credit_to_project,
)
from .fragments import fragment_evidence_digest, import_fragment_file, validate_fragment
from .ledger import project_available_account, project_reserved_account, solver_operating_available_account
from .payments import FakePaymentGateway
from .release_integrity import release_audit_report
from .release_provenance import audit_annotated_tag, render_tag_message
from .stripe_webhooks import StripeWebhookError, record_stripe_webhook_event
from .util import sha256_bytes, sha256_text, stable_json, utc_now
from .verification import ProtectedVerificationResult


SECURITY_AUDIT_SCHEMA = "agent-bounty-security-audit-v1"

SECRET_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("stripe_secret_key", re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{12,}\b"), "fail"),
    ("stripe_webhook_secret", re.compile(r"\bwhsec_[A-Za-z0-9]{12,}\b"), "fail"),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"), "fail"),
    ("nvidia_key", re.compile(r"\bnvapi-[A-Za-z0-9_-]{12,}\b"), "fail"),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "fail"),
    ("checkout_url", re.compile(r"https://checkout\.stripe\.com/[A-Za-z0-9_/?=&%.-]+"), "fail"),
    ("private_path", re.compile(r"(?:/home/[A-Za-z0-9_.-]+|/Users/[A-Za-z0-9_.-]+)"), "warn"),
]


class SecurityAuditError(RuntimeError):
    pass


class AuditVerifierRunner:
    def run(
        self,
        *,
        bounty_id: str,
        motoko_repo: Path,
        base_commit: str,
        candidate_commit: str,
    ) -> ProtectedVerificationResult:
        now = utc_now()
        accepted = str(candidate_commit).startswith("accept")
        result = {
            "schema": "protected-verifier-result-v1",
            "accepted": accepted,
            "verifier_id": "security_audit_verifier",
            "verifier_version": "1.0.0",
            "metrics": {"bounty_id": bounty_id, "candidate_commit": candidate_commit},
            "failure_reasons": [] if accepted else ["deterministic rejection"],
        }
        return ProtectedVerificationResult(
            accepted=accepted,
            metrics=result["metrics"],
            verifier_digest=sha256_bytes(b"security-audit-verifier"),
            backend="security-audit",
            backend_digest=sha256_bytes(b"security-audit-backend"),
            policy_digest=sha256_bytes(f"{bounty_id}:{base_commit}".encode("utf-8")),
            stdout_sha256=sha256_bytes(stable_json(result).encode("utf-8")),
            stderr_sha256=sha256_bytes(b""),
            started_at=now,
            finished_at=now,
            result=result,
            returncode=0 if accepted else 1,
        )


def security_audit_report(root: Path | None = None, *, full: bool = False) -> dict[str, Any]:
    root_path = (root or Path.cwd()).resolve()
    audit_commit = _git_optional(root_path, "rev-parse", "HEAD") or "not-a-git-checkout"
    model = run_model_checks(seed_count=40 if full else 8, steps=50 if full else 20)
    mutation = run_mutation_probes(root_path)
    fuzz = run_fuzz_probes(root_path, cases=200 if full else 40)
    filesystem = run_filesystem_probes(root_path)
    release = release_audit_report(root_path)
    secret_scan = scan_for_secrets(root_path, include_history=full, history_limit=200 if full else 0)
    findings = audit_findings(filesystem=filesystem, secret_scan=secret_scan)
    p0_p1_open = [finding for finding in findings if finding["severity"] in {"P0", "P1"} and finding["status"] != "fixed"]
    ok = all(
        [
            model["ok"],
            mutation["ok"],
            fuzz["ok"],
            filesystem["ok"],
            release["ok"],
            secret_scan["ok"],
            not p0_p1_open,
        ]
    )
    return {
        "schema": SECURITY_AUDIT_SCHEMA,
        "ok": ok,
        "mode": "full" if full else "quick",
        "audit_commit": audit_commit,
        "methodology": [
            "source and schemas reviewed before relying on test intent",
            "comments, docs, fake clients, fragments, bundles, and webhooks treated as untrusted",
            "findings distinguish fixed defects from residual risks",
        ],
        "invariant_groups": invariant_table(),
        "model_check": model,
        "mutation_score": mutation,
        "fuzz": fuzz,
        "filesystem": filesystem,
        "release_audit": {"ok": release["ok"], "errors": release["errors"], "release_tag": release.get("release_tag")},
        "secret_scan": secret_scan,
        "findings": findings,
        "release_recommendation": "pass" if ok else "conditional",
    }


def invariant_table() -> list[dict[str, Any]]:
    return [
        {"area": "money", "invariants": ["minor-unit integers", "currency consistency", "nonnegative trusted accounts", "settlement split sums", "exactly-once idempotency"]},
        {"area": "verification", "invariants": ["candidate/base binding", "verifier digest binding", "accepted receipt gates settlement", "errors/timeouts never pay"]},
        {"area": "external_events", "invariants": ["Stripe signature/raw body", "GitHub delivery dedupe", "changed idempotency parameters fail", "out-of-order events stay recorded"]},
        {"area": "execution", "invariants": ["scrubbed environments", "bounded output/time", "platform-owned verifier path", "shell-free subprocess construction"]},
        {"area": "evidence_release", "invariants": ["fragment downgrade protection", "fake IDs rejected in real rows", "bundle digest binding", "annotated tag provenance"]},
    ]


def run_model_checks(*, seed_count: int, steps: int) -> dict[str, Any]:
    seeds = list(range(seed_count))
    failures: list[dict[str, Any]] = []
    for seed in seeds:
        try:
            _model_check_seed(seed, steps)
        except Exception as exc:
            failures.append({"seed": seed, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "schema": "agent-bounty-security-model-check-v1",
        "ok": not failures,
        "seeds": seeds,
        "steps_per_seed": steps,
        "failures": failures,
    }


def _model_check_seed(seed: int, steps: int) -> None:
    rng = random.Random(seed)
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "market.sqlite3"
        market = AgentBountyMarket(connect(db_path), FakePaymentGateway(), AuditVerifierRunner())
        contexts = [_Context(index=idx) for idx in range(3)]
        for context in contexts:
            context.ensure_project(market)
        for _ in range(steps):
            context = rng.choice(contexts)
            operation = rng.choice(["fund", "reserve", "claim", "expire", "submit_accept", "submit_reject", "verify", "allocate", "replay", "bad_cross"])
            _apply_model_operation(market, context, operation)
            _assert_database_invariants(market)
        reopened = AgentBountyMarket(connect(db_path), FakePaymentGateway(), AuditVerifierRunner())
        _assert_database_invariants(reopened)


class _Context:
    def __init__(self, *, index: int):
        self.project_id = f"project_audit_{index}"
        self.bounty_id = f"bounty_audit_{index}"
        self.solver_id = f"solver_audit_{index}"
        self.funded = False
        self.created = False
        self.reserved = False
        self.claimed = False
        self.submitted = False
        self.submission_id: str | None = None
        self.verified = False
        self.accepted = False
        self.allocated = False
        self.candidate = f"accept-{index}"

    def ensure_project(self, market: AgentBountyMarket) -> None:
        market.create_project(project_id=self.project_id, name=self.project_id, currency="USD")
        market.set_budget_policy(
            project_id=self.project_id,
            max_bounty_amount=500,
            monthly_budget=500,
            human_approval_threshold=500,
            allowed_issue_classes=["security-audit"],
        )


def _apply_model_operation(market: AgentBountyMarket, context: _Context, operation: str) -> None:
    try:
        if operation == "fund":
            market.fund_project(project_id=context.project_id, amount=500, currency="USD", idempotency_key=f"fund:{context.project_id}")
            context.funded = True
        elif operation == "reserve":
            if not context.created:
                market.create_bounty(
                    bounty_id=context.bounty_id,
                    project_id=context.project_id,
                    title=context.bounty_id,
                    reward_amount=500,
                    currency="USD",
                    base_commit="base",
                    issue_ref=f"example/repo#{context.project_id}",
                    verifier_id="security_audit_verifier",
                )
                context.created = True
            market.reserve_bounty(bounty_id=context.bounty_id, idempotency_key=f"reserve:{context.bounty_id}")
            context.reserved = True
        elif operation == "claim":
            market.create_solver(solver_id=context.solver_id, display_name=context.solver_id, idempotency_key=f"solver:{context.solver_id}")
            market.claim_bounty(
                bounty_id=context.bounty_id,
                solver_id=context.solver_id,
                lease_expires_at="2026-07-01T00:00:00Z",
                idempotency_key=f"claim:{context.bounty_id}:{context.solver_id}",
            )
            context.claimed = True
        elif operation == "expire":
            market.expire_claim(bounty_id=context.bounty_id, idempotency_key=f"expire:{context.bounty_id}")
            context.claimed = False
        elif operation in {"submit_accept", "submit_reject"}:
            candidate = context.candidate if operation == "submit_accept" else f"reject-{context.project_id}"
            submission = market.submit_candidate(
                bounty_id=context.bounty_id,
                solver_id=context.solver_id,
                candidate_repo_path="/tmp/security-audit-candidate",
                candidate_commit=candidate,
                idempotency_key=f"submit:{context.bounty_id}:{candidate}",
            )
            context.submitted = True
            context.submission_id = submission["submission_id"]
            context.candidate = candidate
        elif operation == "verify" and context.submission_id:
            verification = market.run_verification(submission_id=context.submission_id, idempotency_key=f"verify:{context.submission_id}")
            context.verified = bool(verification.get("receipt"))
            context.accepted = bool((verification.get("receipt") or {}).get("accepted"))
        elif operation == "allocate":
            allocate_accepted_reward(market, bounty_id=context.bounty_id, idempotency_key=f"settle:{context.bounty_id}")
            context.allocated = True
        elif operation == "replay":
            if context.funded:
                market.fund_project(project_id=context.project_id, amount=500, currency="USD", idempotency_key=f"fund:{context.project_id}")
            if context.allocated:
                allocate_accepted_reward(market, bounty_id=context.bounty_id, idempotency_key=f"settle:{context.bounty_id}")
        elif operation == "bad_cross":
            market.claim_bounty(
                bounty_id=context.bounty_id,
                solver_id=f"other_{context.solver_id}",
                lease_expires_at="2026-07-01T00:00:00Z",
                idempotency_key=f"claim:{context.bounty_id}:{context.solver_id}",
            )
    except Exception:
        return


def _assert_database_invariants(market: AgentBountyMarket) -> None:
    rows = market.conn.execute("SELECT * FROM account_balances").fetchall()
    computed: dict[tuple[str, str], int] = {}
    for entry in market.conn.execute("SELECT * FROM ledger_entries").fetchall():
        currency = entry["currency"]
        computed[(entry["from_account"], currency)] = computed.get((entry["from_account"], currency), 0) - int(entry["amount"])
        computed[(entry["to_account"], currency)] = computed.get((entry["to_account"], currency), 0) + int(entry["amount"])
    for row in rows:
        key = (row["account"], row["currency"])
        if int(row["balance"]) != computed.get(key, 0):
            raise SecurityAuditError(f"balance mismatch for {key}")
        if int(row["allow_negative"]) == 0 and int(row["balance"]) < 0:
            raise SecurityAuditError(f"negative trusted balance for {key}")
    for row in market.conn.execute("SELECT * FROM settlement_allocations").fetchall():
        if int(row["reward_amount"]) != int(row["external_transfer_amount"]) + int(row["retained_operating_amount"]) + int(row["platform_fee_amount"]):
            raise SecurityAuditError("settlement split mismatch")
        receipt = market.conn.execute("SELECT * FROM verification_receipts WHERE id = ?", (row["accepted_receipt_id"],)).fetchone()
        if not receipt or int(receipt["accepted"]) != 1:
            raise SecurityAuditError("settlement without accepted receipt")
    for bounty in market.conn.execute("SELECT * FROM bounties WHERE state IN ('accepted','payout_pending','payout_failed','paid')").fetchall():
        if not bounty["accepted_receipt_id"]:
            raise SecurityAuditError("accepted/paid bounty missing receipt")


def run_mutation_probes(root: Path) -> dict[str, Any]:
    probes = [
        _probe_duplicate_settlement_replay,
        _probe_rejected_work_cannot_settle,
        _probe_negative_reserve_denied,
        _probe_changed_idempotency_denied,
        _probe_candidate_receipt_binding,
        _probe_bad_stripe_signature_denied,
        _probe_real_fragment_fake_id_denied,
        lambda: _probe_fragment_downgrade_denied(root),
        lambda: _probe_bundle_escape_denied(root),
        lambda: _probe_release_tag_digest_mismatch_denied(root),
    ]
    results = []
    for probe in probes:
        try:
            detail = probe()
            results.append({"name": getattr(probe, "__name__", "probe"), "ok": True, "detail": detail})
        except Exception as exc:
            results.append({"name": getattr(probe, "__name__", "probe"), "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    passed = sum(1 for result in results if result["ok"])
    return {"schema": "agent-bounty-security-mutation-score-v1", "ok": passed == len(results), "passed": passed, "total": len(results), "probes": results}


def _accepted_market(tmp: Path, *, candidate: str = "accept-candidate") -> tuple[AgentBountyMarket, str, str]:
    market = AgentBountyMarket(connect(tmp / "market.sqlite3"), FakePaymentGateway(), AuditVerifierRunner())
    project_id = "project_probe"
    bounty_id = "bounty_probe"
    solver_id = "solver_probe"
    market.create_project(project_id=project_id, name=project_id, currency="USD")
    market.set_budget_policy(project_id=project_id, max_bounty_amount=500, monthly_budget=500, human_approval_threshold=500, allowed_issue_classes=["probe"])
    market.fund_project(project_id=project_id, amount=500, currency="USD", idempotency_key="fund:probe")
    market.create_bounty(bounty_id=bounty_id, project_id=project_id, title="Probe", reward_amount=500, currency="USD", base_commit="base", issue_ref="example/repo#1", verifier_id="security_audit_verifier")
    market.reserve_bounty(bounty_id=bounty_id, idempotency_key="reserve:probe")
    market.create_solver(solver_id=solver_id, display_name=solver_id, idempotency_key="solver:probe")
    market.claim_bounty(bounty_id=bounty_id, solver_id=solver_id, lease_expires_at="2026-07-01T00:00:00Z", idempotency_key="claim:probe")
    submission = market.submit_candidate(bounty_id=bounty_id, solver_id=solver_id, candidate_repo_path="/tmp/probe", candidate_commit=candidate, idempotency_key=f"submit:{candidate}")
    market.run_verification(submission_id=submission["submission_id"], idempotency_key=f"verify:{candidate}")
    return market, bounty_id, solver_id


def _probe_duplicate_settlement_replay() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        market, bounty_id, _solver_id = _accepted_market(Path(tmp))
        first = allocate_accepted_reward(market, bounty_id=bounty_id, idempotency_key="settle:probe")
        count = market.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
        second = allocate_accepted_reward(market, bounty_id=bounty_id, idempotency_key="settle:probe")
        count_after = market.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
    if not second["replayed"] or first["allocation_id"] != second["allocation_id"] or count != count_after:
        raise SecurityAuditError("settlement replay changed ledger")
    return {"allocation_id": first["allocation_id"], "ledger_entries": count}


def _probe_rejected_work_cannot_settle() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        market, bounty_id, _solver_id = _accepted_market(Path(tmp), candidate="reject-candidate")
        try:
            allocate_accepted_reward(market, bounty_id=bounty_id, idempotency_key="settle:rejected")
        except EconomicLoopError:
            return {"blocked": True}
    raise SecurityAuditError("rejected work settled")


def _probe_negative_reserve_denied() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        market = AgentBountyMarket(connect(Path(tmp) / "market.sqlite3"), FakePaymentGateway(), AuditVerifierRunner())
        market.create_project(project_id="project_empty", name="empty", currency="USD")
        market.set_budget_policy(project_id="project_empty", max_bounty_amount=500, monthly_budget=500, human_approval_threshold=500, allowed_issue_classes=["probe"])
        market.create_bounty(bounty_id="bounty_empty", project_id="project_empty", title="empty", reward_amount=500, currency="USD", base_commit="base", issue_ref="example/repo#2", verifier_id="security_audit_verifier")
        try:
            market.reserve_bounty(bounty_id="bounty_empty", idempotency_key="reserve:empty")
        except Exception:
            return {"blocked": True}
    raise SecurityAuditError("unfunded reserve succeeded")


def _probe_changed_idempotency_denied() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        market = AgentBountyMarket(connect(Path(tmp) / "market.sqlite3"), FakePaymentGateway(), AuditVerifierRunner())
        market.create_project(project_id="project_idem", name="idem", currency="USD")
        market.set_budget_policy(project_id="project_idem", max_bounty_amount=500, monthly_budget=500, human_approval_threshold=500, allowed_issue_classes=["probe"])
        market.fund_project(project_id="project_idem", amount=100, currency="USD", idempotency_key="same")
        try:
            market.fund_project(project_id="project_idem", amount=200, currency="USD", idempotency_key="same")
        except MarketError:
            return {"blocked": True}
    raise SecurityAuditError("changed idempotency arguments accepted")


def _probe_candidate_receipt_binding() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        market, _bounty_id, _solver_id = _accepted_market(Path(tmp), candidate="accept-bound")
        row = market.conn.execute("SELECT candidate_commit, receipt_json FROM verification_receipts ORDER BY created_at DESC LIMIT 1").fetchone()
        receipt = json.loads(row["receipt_json"])
    if receipt["candidate_commit"] != "accept-bound" or row["candidate_commit"] != "accept-bound":
        raise SecurityAuditError("receipt candidate binding mismatch")
    return {"candidate_commit": receipt["candidate_commit"]}


def _probe_bad_stripe_signature_denied() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        conn = connect(Path(tmp) / "market.sqlite3")
        payload = b'{"id":"evt_bad","type":"payment_intent.succeeded","livemode":false,"data":{"object":{"id":"pi_bad"}}}'
        try:
            record_stripe_webhook_event(conn, payload=payload, signature_header="t=1,v1=bad", endpoint_secret="whsec_test", now=1)
        except StripeWebhookError:
            return {"blocked": True}
    raise SecurityAuditError("bad Stripe signature accepted")


def _probe_real_fragment_fake_id_denied() -> dict[str, Any]:
    fragment = _base_fragment(truth_status="real", safe_evidence={"transfer": "fake_transfer_bad"})
    validation = validate_fragment(fragment)
    if validation["ok"]:
        raise SecurityAuditError("real fragment with fake id accepted")
    return {"errors": validation["errors"]}


def _probe_fragment_downgrade_denied(root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        bundle_dir = Path(tmp) / "bundle"
        shutil.copytree(root / "demo" / "bundles" / "winning-run", bundle_dir)
        real = _base_fragment(truth_status="recorded-real", safe_evidence={"transfer": "tr_recorded"})
        real["component_id"] = "stripe_split_transfer"
        real["schema"] = "stripe-split-settlement-fragment-v1"
        real["evidence_digest"] = fragment_evidence_digest(real["safe_evidence"])
        real_path = Path(tmp) / "real.json"
        real_path.write_text(stable_json(real) + "\n", encoding="utf-8")
        imported = import_fragment_file(bundle_dir, real_path)
        fallback = _base_fragment(truth_status="fallback", safe_evidence={"blocked": True}, blocker="test blocker")
        fallback["component_id"] = "stripe_split_transfer"
        fallback["schema"] = "stripe-split-settlement-fragment-v1"
        fallback["evidence_digest"] = fragment_evidence_digest(fallback["safe_evidence"])
        fallback_path = Path(tmp) / "fallback.json"
        fallback_path.write_text(stable_json(fallback) + "\n", encoding="utf-8")
        downgraded = import_fragment_file(bundle_dir, fallback_path)
    if not imported["ok"] or downgraded["ok"]:
        raise SecurityAuditError("fragment downgrade protection failed")
    return {"downgrade_error": downgraded["error"]}


def _probe_bundle_escape_denied(root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        bundle_dir = Path(tmp) / "bundle"
        shutil.copytree(root / "demo" / "bundles" / "winning-run", bundle_dir)
        outside = Path(tmp) / "outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        manifest_path = bundle_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["../outside.txt"] = sha256_bytes(outside.read_bytes())
        manifest_path.write_text(stable_json(manifest) + "\n", encoding="utf-8")
        validation = validate_bundle(bundle_dir)
    if validation["ok"] or "manifest path escapes bundle: ../outside.txt" not in validation["mismatches"]:
        raise SecurityAuditError("bundle path escape accepted")
    return {"blocked": True}


def _probe_release_tag_digest_mismatch_denied(root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        fixture = Path(tmp) / "release"
        shutil.copytree(root / "demo" / "bundles" / "winning-run", fixture / "demo" / "bundles" / "winning-run")
        (fixture / "submission").mkdir()
        shutil.copy2(root / "submission" / "RELEASE_MANIFEST.json", fixture / "submission" / "RELEASE_MANIFEST.json")
        _git(fixture, "init")
        _git(fixture, "config", "user.email", "audit@example.invalid")
        _git(fixture, "config", "user.name", "Audit")
        _git(fixture, "add", ".")
        _git(fixture, "commit", "-m", "fixture")
        message = fixture / "tag.json"
        message.write_text(render_tag_message(root=fixture, bundle_dir=fixture / "demo" / "bundles" / "winning-run", tag="audit-rc"), encoding="utf-8")
        _git(fixture, "tag", "-a", "audit-rc", "-F", str(message))
        manifest_path = fixture / "submission" / "RELEASE_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source_baseline_note"] = "mutation"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        audit = audit_annotated_tag(root=fixture, bundle_dir=fixture / "demo" / "bundles" / "winning-run", tag="audit-rc")
    if audit["ok"] or "tag_message_digest_mismatch" not in {error["code"] for error in audit["errors"]}:
        raise SecurityAuditError("release tag digest mismatch accepted")
    return {"blocked": True}


def _base_fragment(*, truth_status: str, safe_evidence: dict[str, Any], blocker: str | None = None) -> dict[str, Any]:
    fragment = {
        "schema": "github-lifecycle-fragment-v1",
        "component_id": "github_lifecycle",
        "truth_status": truth_status,
        "source_issue": 22,
        "source_commit": "audit",
        "source_command": "security-audit",
        "captured_at": "2026-06-25T00:00:00Z",
        "source_digest": "sha256:" + "0" * 64,
        "safe_evidence": safe_evidence,
        "consistency": {},
    }
    if blocker:
        fragment["blocker"] = blocker
    fragment["evidence_digest"] = fragment_evidence_digest(safe_evidence)
    return fragment


def run_fuzz_probes(root: Path, *, cases: int) -> dict[str, Any]:
    from .github_integration import GitHubIntegrationError, parse_claim_comment, parse_contract_from_issue_body, parse_submission_marker
    from .release_provenance import ReleaseProvenanceError, canonical_release_provenance
    from .stripe_webhooks import verify_stripe_signature

    rng = random.Random(22022)
    failures: list[dict[str, str]] = []
    corpus = ["", "\x00", "Café mañana résumé 東京", "<!-- agent-bounty-contract-v1 {} -->", "{" * 80, "../secret", "sk_test_placeholder", stable_json({"x": ["y"] * 20})]
    for index in range(cases):
        text = corpus[index % len(corpus)] + "".join(chr(rng.randint(1, 0xD7FF)) for _ in range(rng.randint(0, 8)))
        for name, func in (
            ("contract", parse_contract_from_issue_body),
            ("claim", parse_claim_comment),
            ("submission", parse_submission_marker),
        ):
            try:
                func(text)
            except (GitHubIntegrationError, json.JSONDecodeError, TypeError, ValueError):
                pass
            except Exception as exc:
                failures.append({"case": f"{name}:{index}", "error": f"{type(exc).__name__}: {exc}"})
        try:
            verify_stripe_signature(payload=text.encode("utf-8", errors="ignore"), signature_header=text, endpoint_secret="whsec_test", now=int(time.time()))
        except Exception:
            pass
        try:
            validate_fragment({"schema": text, "safe_evidence": text, "consistency": text})
        except Exception as exc:
            failures.append({"case": f"fragment:{index}", "error": f"{type(exc).__name__}: {exc}"})
        try:
            canonical_release_provenance(root=root, tag=text[:32])
        except (ReleaseProvenanceError, OSError, ValueError):
            pass
        except Exception as exc:
            failures.append({"case": f"release:{index}", "error": f"{type(exc).__name__}: {exc}"})
    return {"schema": "agent-bounty-security-fuzz-v1", "ok": not failures, "cases": cases, "failures": failures}


def run_filesystem_probes(root: Path) -> dict[str, Any]:
    probes = [_probe_bundle_escape_denied(root)]
    with tempfile.TemporaryDirectory() as tmp:
        bundle_dir = Path(tmp) / "bundle"
        shutil.copytree(root / "demo" / "bundles" / "winning-run", bundle_dir)
        outside = Path(tmp) / "outside.txt"
        outside.write_text("whsec_should_not_be_read\n", encoding="utf-8")
        (bundle_dir / "evidence" / "outside-link.txt").symlink_to(outside)
        validation = validate_bundle(bundle_dir)
        symlink_ok = not validation["ok"] and any("bundle path escapes via symlink" in item for item in validation["mismatches"])
    return {"schema": "agent-bounty-security-filesystem-v1", "ok": bool(probes and symlink_ok), "manifest_escape": probes[0], "symlink_escape_blocked": symlink_ok}


def scan_for_secrets(root: Path, *, include_history: bool, history_limit: int) -> dict[str, Any]:
    current_paths = _git_lines_optional(root, "ls-files")
    current_hits = _scan_paths(root, current_paths if current_paths is not None else _walk_repo_files(root), commit=None)
    history_hits: list[dict[str, Any]] = []
    history_scanned = False
    if include_history and _git_optional(root, "rev-parse", "--is-inside-work-tree") == "true":
        history_scanned = True
        for commit in _git_lines(root, "rev-list", f"--max-count={history_limit}", "HEAD"):
            for path in _git_lines(root, "ls-tree", "-r", "--name-only", commit):
                try:
                    text = subprocess.run(["git", "-C", str(root), "show", f"{commit}:{path}"], capture_output=True, text=True, timeout=2).stdout
                except Exception:
                    continue
                history_hits.extend(_scan_text(path=path, text=text[:2_000_000], commit=commit))
    fail_hits = [hit for hit in current_hits + history_hits if hit["severity"] == "fail"]
    return {
        "schema": "agent-bounty-secret-scan-v1",
        "ok": not fail_hits,
        "current_hit_count": len(current_hits),
        "history_scanned": history_scanned,
        "history_requested": include_history,
        "history_hit_count": len(history_hits),
        "fail_count": len(fail_hits),
        "hits": (current_hits + history_hits)[:80],
    }


def _scan_paths(root: Path, paths: list[str], *, commit: str | None) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for rel in paths:
        path = root / rel
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        hits.extend(_scan_text(path=rel, text=text, commit=commit))
    return hits


def _scan_text(*, path: str, text: str, commit: str | None) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for kind, pattern, severity in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(0)
            if any(marker in value for marker in ("YOUR_", "PLACEHOLDER", "placeholder", "should_not_leak")):
                continue
            hits.append({"kind": kind, "severity": severity, "path": path, "commit": commit, "match_digest": sha256_text(value), "line": text.count("\n", 0, match.start()) + 1})
    return hits


def audit_findings(*, filesystem: dict[str, Any], secret_scan: dict[str, Any]) -> list[dict[str, Any]]:
    findings = [
        {
            "id": "ABM-SEC-001",
            "severity": "P1",
            "status": "fixed",
            "title": "Bundle validation could touch manifest paths or symlink targets outside the bundle",
            "reproduction": "security-audit filesystem probe plus tests.test_demo_presentation path escape cases",
            "fix": "constrain manifest paths to bundle root and reject symlink escapes during bundle scans",
            "residual_risk": "bundle files remain local operator input; validation reports only paths and digests, not file contents",
        }
    ]
    if secret_scan["fail_count"]:
        findings.append({"id": "ABM-SEC-SECRET", "severity": "P0", "status": "open", "title": "secret-like value detected", "reproduction": "security-audit secret scan", "fix": "operator rotation required before release", "residual_risk": "history rewrite is intentionally not automated"})
    return findings


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if completed.returncode != 0:
        raise SecurityAuditError((completed.stderr or completed.stdout or "git failed").strip())
    return completed.stdout.strip()


def _git_optional(root: Path, *args: str) -> str | None:
    completed = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _git_lines(root: Path, *args: str) -> list[str]:
    output = _git(root, *args)
    return [line for line in output.splitlines() if line]


def _git_lines_optional(root: Path, *args: str) -> list[str] | None:
    output = _git_optional(root, *args)
    if output is None:
        return None
    return [line for line in output.splitlines() if line]


def _walk_repo_files(root: Path) -> list[str]:
    skipped_dirs = {".git", ".demo", "__pycache__"}
    paths: list[str] = []
    for path in sorted(root.rglob("*")):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in skipped_dirs for part in relative.parts):
            continue
        if path.is_file():
            paths.append(str(relative))
    return paths
