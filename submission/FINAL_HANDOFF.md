# Final Handoff

Release candidate tag: `hackathon-mixed-rc7`

This release candidate is a truthful mixed real/fallback demo package. It does
not claim a complete sponsor-integrated live run. It packages the strongest
available evidence into `demo/bundles/winning-run` with a machine-readable truth
matrix, digest manifest, static dashboard, and hashed attestation.

## Product Pitch

Agent Bounty Market turns neglected software tasks into funded, verified,
replay-safe work performed by specialized agents.

## Winning Bundle

```bash
nix develop --command python3 -m agent_bounty demo-build-winning-run \
  --db .demo/winning-run.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency \
  --bundle demo/bundles/winning-run

nix develop --command python3 -m agent_bounty submission-check

nix develop --command python3 -m agent_bounty release-audit --tag hackathon-mixed-rc7

nix develop --command python3 -m agent_bounty demo-rehearse \
  --mode replay \
  --bundle demo/bundles/winning-run \
  --repeat 5

nix develop --command python3 -m agent_bounty demo-serve \
  --bundle demo/bundles/winning-run \
  --host 127.0.0.1 \
  --port 8787 \
  --check
```

Bundle files:

- `manifest.json`: file digests and attestation digest.
- `bundle.json`: sanitized persisted run data, summary, timeline, consistency
  fields, and truth matrix.
- `attestation.json`: hashed attestation only; no private signing key was
  created.
- `dashboard.html`: static recording surface.
- `recording-timeline.md`: deterministic two-minute recording cues.
- `evidence/*.json`: compact evidence slices for truth matrix, demo summary,
  and database counts.

Fragment upgrades:

- templates: `demo/fragments/templates/`
- docs: `docs/fragment-import.md`
- commands: `fragment validate`, `fragment import`, `fragment list`, and
  `fragment build-winning`

Live setup:

- command: `python -m agent_bounty live-setup-wizard --format json`
- runbook: `submission/LIVE_SETUP_RUNBOOK.md`
- live preflight shares the wizard blocker list:
  `python -m agent_bounty demo-preflight --mode live`
- red-team gate: `python -m agent_bounty submission-check`
- release gate: `python -m agent_bounty release-audit --tag hackathon-mixed-rc7`
- judge Q&A: `submission/JUDGE_QA.md`
- sponsor matrix: `submission/SPONSOR_INTEGRATION.md`
- release checklist: `submission/RELEASE_CHECKLIST.md`
- release manifest: `submission/RELEASE_MANIFEST.json`

Backup bundle:

```bash
nix develop --command python3 -m agent_bounty demo-build-winning-run \
  --db .demo/release-backups/hackathon-mixed-rc7.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency \
  --bundle .demo/release-backups/hackathon-mixed-rc7
```

The backup path is intentionally under ignored `.demo/` state. Regenerate it
from the command above instead of committing generated databases.

## Truth Matrix

Current truth status:

- `real`: Hermes executable/version is installed and inspectable locally.
- `recorded-real`: prior Stripe sandbox full-transfer fragment is documented in
  `docs/chatgpt-pro-stripe-blocker-report.md`.
- `fallback`: project-agent decision, solver-agent decision, and retained-credit
  spend use deterministic fallback paths.
- `blocked`: NVIDIA/Nemotron, OpenShell/NemoClaw, real GitHub lifecycle, and a
  fresh real split Stripe Connect Transfer are blocked by missing external
  credentials/runtime/configuration in this process.

The dashboard must show `Mixed real/fallback`. A fallback or fake-provider
component cannot be relabeled as live without failing validation.

## Release Provenance v2

Release provenance is now tag-authoritative:

- `submission/RELEASE_MANIFEST.json` records stable bundle digests and the
  intended release tag.
- The manifest intentionally does not record a self-referential current commit
  SHA. The annotated Git tag target is the immutable release pointer.
- The canonical tag message is rendered with:

```bash
nix develop --command python3 -m agent_bounty release-provenance render-tag-message --tag hackathon-mixed-rc7
```

- The final release gate is:

```bash
nix develop --command python3 -m agent_bounty release-audit --tag hackathon-mixed-rc7
```

Issue #21 was dogfooded through the local market core with retained operating
credit. The sanitized evidence is generated under ignored `.demo/` state and
reported in the issue handoff instead of being committed, because it binds to
the exact candidate SHA it verifies.

## Current Blockers

1. NVIDIA/Nemotron:
   - `NVIDIA_API_KEY` is not present.
   - No real Nemotron-backed Hermes decision run is claimed.

2. OpenShell/NemoClaw:
   - `docker` and `openshell` are not available on `PATH`.
   - No real sandbox execution is claimed.

3. GitHub lifecycle:
   - Missing `AGENT_BOUNTY_GITHUB_INTEGRATION=1`.
   - Missing `AGENT_BOUNTY_GITHUB_TOKEN` or `GH_TOKEN`.
   - Missing `AGENT_BOUNTY_GITHUB_REPOSITORY`.
   - Missing `AGENT_BOUNTY_GITHUB_WEBHOOK_SECRET`.
   - No real issue update, claim comment, PR, status, or webhook delivery is
     claimed.

4. Fresh split Stripe settlement:
   - This process has no loaded Stripe sandbox env:
     `AGENT_BOUNTY_STRIPE_SANDBOX=1`, `STRIPE_TEST_SECRET_KEY`,
     `STRIPE_TEST_WEBHOOK_SECRET`, and `STRIPE_TEST_CONNECTED_ACCOUNT_ID`.
   - The reviewed split adapter exists, but no fresh real split Connect Transfer
     is claimed from this pass.

## Safe Stripe Evidence

Prior real Stripe sandbox full-transfer evidence is recorded in
`docs/chatgpt-pro-stripe-blocker-report.md`.

Safe object IDs from that run:

```text
PaymentIntent: pi_3Tleim2MCkccMoa914w0sD0C
Charge: ch_3Tleim2MCkccMoa91pVUsdmF
Funding event: evt_3Tleim2MCkccMoa91oxQFSP4
Connected account: acct_1TlaGA2MCkdsU43l
Transfer: tr_3Tleim2MCkccMoa91ZC6yBOQ
Transfer audit event: evt_3Tleim2MCkccMoa91tozrj04
Currency: EUR
```

## Validation

Final validation command set:

```bash
nix develop --command python3 -m py_compile agent_bounty/demo_presentation.py agent_bounty/release_integrity.py agent_bounty/cli.py tests/test_release_integrity.py
nix develop --command python3 -m unittest tests.test_release_integrity
nix develop --command python3 -m agent_bounty demo-build-winning-run --db .demo/winning-run.sqlite3 --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency --bundle demo/bundles/winning-run
nix develop --command python3 -m agent_bounty submission-check
nix develop --command python3 -m agent_bounty release-audit --tag hackathon-mixed-rc7
nix develop --command python3 -m agent_bounty demo-rehearse --mode replay --bundle demo/bundles/winning-run --repeat 5
nix develop --command python3 -m agent_bounty demo-serve --bundle demo/bundles/winning-run --host 127.0.0.1 --port 8787 --check
nix develop --command python3 -m compileall agent_bounty tests verifiers
nix develop --command python3 -m unittest discover -s tests
nix flake check
git diff --check
```

Observed before final commit:

```text
focused release-integrity tests: 7 passed
winning bundle validation: ok=true, mode=mixed, truth=mixed-real-fallback
submission-check: ok=true, errors=[]
release-audit: ok=true, errors=[]
replay rehearsal: 5/5 validations passed
serve check: ok=true, url=http://127.0.0.1:8787/dashboard.html
director check: ok=true, url=http://127.0.0.1:8788/director.html?duration=120
bundle digest: sha256:5ab1df5b9d1f901008c7425bebf10df9895748a77e454ea58a0fd01355625cf6
attestation digest: sha256:11554b3999fe144cb804c941a3a6cb48fd53729fd8ce1c19fc05bdc6ccf6aa0b
truth matrix digest: sha256:bc769442f2102ee2ddad06a84b35f6c992fef227a7b579ba71979df9922d3e07
full suite: 184 tests passed, 2 skipped
nix flake check: all checks passed
```

## Recording

Use `submission/RECORDING_RUNBOOK.md`. Serve
`demo/bundles/winning-run/dashboard.html` with `demo-serve`, keep the
`Mixed real/fallback` badge visible, and say the blockers plainly.

## Submission Checklist

- [x] Truthful mixed winning bundle captured.
- [x] Truth matrix included in bundle and evidence directory.
- [x] Static dashboard generated from persisted records.
- [x] Repeated replay rehearsal implemented and tested.
- [x] Submission red-team checker added.
- [x] Release audit checker added.
- [x] Release manifest and checklist added.
- [x] Private local paths scrubbed from generated bundle artifacts.
- [x] Judge Q&A, short scripts, and sponsor matrix added.
- [x] Fake/test IDs in real rows are rejected.
- [x] Currency/receipt consistency drift is rejected.
- [x] Secret-like bundle contents are rejected.
- [x] Prior real Stripe sandbox evidence is referenced.
- [x] Full tests pass.
- [x] Nix flake check passes.
- [ ] Complete sponsor-integrated live run captured.
