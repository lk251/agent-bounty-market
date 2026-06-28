# Final Handoff

Release candidate tag: `hackathon-mixed-rc10`

The committed release manifest is prepared for the annotated
`hackathon-mixed-rc10` tag. Create the tag only after the Linux/Nix release
gate and operator pre/post state check pass on the immutable release commit,
then run the tag-aware release audit.

This release candidate is a truthful mixed real/fallback demo package. It does
not claim a complete sponsor-integrated live run. It packages the strongest
available evidence into `demo/bundles/winning-run` with a machine-readable truth
matrix, digest manifest, static dashboard, and hashed attestation.

## Product Pitch

Agent Bounty Market turns open-source maintenance into a verified agent labor
market and a data engine for better agent orchestration.

## Winning Bundle

```bash
nix develop --command python3 -m agent_bounty demo-build-winning-run \
  --db .demo/winning-run.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency \
  --bundle demo/bundles/winning-run

nix develop --command python3 -m agent_bounty submission-check
nix develop --command python3 -m agent_bounty submission-check --entry
nix develop --command python3 -m agent_bounty submission-finalize \
  --state .demo/operator-submission.json \
  --output .demo/final-submission \
  --check
nix develop --command python3 -m agent_bounty submission-check \
  --entry \
  --prepost

nix develop --command python3 -m agent_bounty release-audit --tag hackathon-mixed-rc10

nix develop --command python3 -m agent_bounty demo-rehearse \
  --mode replay \
  --bundle demo/bundles/winning-run \
  --repeat 5

nix develop --command python3 -m agent_bounty demo-director \
  --bundle demo/bundles/winning-run \
  --host 127.0.0.1 \
  --port 8788 \
  --duration 120 \
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
- `director.html`: presenter view with notes.
- `director-record.html`: clean capture route.
- `director-notes.html`: off-screen presenter notes.
- `director-cues.json`: machine-readable scene timing.
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
- operator gate: `python -m agent_bounty submission-finalize --state
  .demo/operator-submission.json --output .demo/final-submission --check`
- prepost gate: `python -m agent_bounty submission-check --entry --prepost`
- release gate: `python -m agent_bounty release-audit --tag hackathon-mixed-rc10`
- judge Q&A: `submission/JUDGE_QA.md`
- sponsor matrix: `submission/SPONSOR_INTEGRATION.md`
- release checklist: `submission/RELEASE_CHECKLIST.md`
- release manifest: `submission/RELEASE_MANIFEST.json`

Backup bundle:

```bash
nix develop --command python3 -m agent_bounty demo-build-winning-run \
  --db .demo/release-backups/hackathon-mixed-rc10.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency \
  --bundle .demo/release-backups/hackathon-mixed-rc10
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
nix develop --command python3 -m agent_bounty release-provenance render-tag-message --tag hackathon-mixed-rc10
```

- The final release gate is:

```bash
nix develop --command python3 -m agent_bounty release-audit --tag hackathon-mixed-rc10
```

Issue #21 was dogfooded through the local market core with retained operating
credit. The sanitized evidence is generated under ignored `.demo/` state and
reported in the issue handoff instead of being committed, because it binds to
the exact candidate SHA it verifies.

## Issue #29 Handoff Status

Issue #29 is implemented on local branch `codex/issue-29-story-flywheel`.
HB3 regenerated the release bundle with the Motoko fixture and passed the
Linux/Nix release gate before the final rc10 commit. The remaining closeout
steps are to create the annotated tag on that final commit, run the tag-aware
release audit, push branch/tag, and close the issue with validation evidence.

Implementation commits prepared before this status note:

- `bfc5b96` - issue #29 story/flywheel implementation, regenerated bundle, and
  updated submission copy.
- `9da51ab` - HB2 native-Windows validation fixes and release handoff updates.

No completion comment has been posted yet, and issue #29 should not be closed
until the annotated tag audit passes.

Settlement shown on screen:

- reward: `$25.00`
- solver wallet operating credit: `$20.00`
- human/operator payout through the Stripe settlement path: `$5.00`

Wording replacements made:

- the old idle verifier shorthand was replaced in judge-facing copy with
  original/superficial/final verifier language.
- the old reward/cap internal error was replaced with project spending-cap
  language.
- the old remaining-reserve internal error was replaced with project reserve
  language.
- the old alternatives-decline subtitle was replaced with project-agent funding
  and verifier-backed work language.

Proof commands:

```bash
STALE_RE="$(printf '%s|' \
  'idle''-only' \
  'Idle''-only' \
  'Reward exceeds maximum ''bounty amount' \
  'reward exceeds maximum ''bounty amount' \
  'Minimum remaining reserve ''would be violated' \
  'minimum remaining reserve ''would be violated' \
  'Policy and budget select one bounded bounty while alternatives ''can decline' \
  'alternatives ''can decline')"
rg -n "${STALE_RE%|}" README.md submission demo/bundles/winning-run
rg -n "Operating credit|Operator payout|external_transfer_amount|retained_operating_amount" demo/bundles/winning-run/dashboard.html demo/bundles/winning-run/bundle.json submission/DEMO_SCRIPT.md submission/JUDGE_QA.md
```

The first command should return no judge-facing stale wording. The second should
show the reversed `$25 / $20 / $5` split and the persisted
`external_transfer_amount=500`, `retained_operating_amount=2000` evidence.

Remaining issue #29 closeout after this commit:

- Create the immutable annotated `hackathon-mixed-rc10` tag from this commit.
- Run `release-audit --tag hackathon-mixed-rc10`.
- Push the branch/tag, comment on issue #29 with the final validation evidence,
  and close issue #29 only after that completion gate is satisfied.

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
nix develop --command python3 -m agent_bounty submission-check --entry
nix develop --command python3 -m agent_bounty submission-finalize --state .demo/operator-submission.json --output .demo/final-submission --check
nix develop --command python3 -m agent_bounty submission-check --entry --prepost
nix develop --command python3 -m agent_bounty release-audit --tag hackathon-mixed-rc10
nix develop --command python3 -m agent_bounty demo-rehearse --mode replay --bundle demo/bundles/winning-run --repeat 5
nix develop --command python3 -m agent_bounty demo-director --bundle demo/bundles/winning-run --host 127.0.0.1 --port 8788 --duration 120 --check
nix develop --command python3 -m compileall agent_bounty tests verifiers
nix develop --command python3 -m unittest discover -s tests
nix flake check
git diff --check
```

Observed on HB3 before final rc10 commit:

```text
focused tests: 75 passed
py_compile focused release files: passed
winning bundle validation: ok=true, mode=mixed, truth=mixed-real-fallback
submission-check: ok=true, errors=[]
submission-check --entry: ok=true, placeholders remain by design
submission-finalize --check: ok=true with ignored local operator state
submission-check --entry --prepost: ok=true with default .demo/operator-submission.json
release-audit: ok=true, errors=[]
release-audit --tag hackathon-mixed-rc10: pending annotated tag creation on the final release commit
stale judge-facing wording scan: no matches in README.md, submission, or demo/bundles/winning-run
replay rehearsal: 5/5 validations passed
director check: ok=true, url=http://127.0.0.1:8788/director.html?duration=120
bundle digest: sha256:c6f777af7f96dfe4ab24d5277afb9f372d01251c99b12b089c156907821f74fc
attestation digest: sha256:3b858055f31df566e3827900137ad75f8c89486128675ed87130bbcc295ef703
truth matrix digest: sha256:d719c1fe6858b5c8a609dfea4eaf2904c61ee3969e8f5aeb0c4e1d03b2bcbb9d
full Linux/Nix unittest suite: 202 tests passed, 2 skipped
nix flake check: passed
git diff --check: passed
```

## Recording

Use `submission/RECORDING_RUNBOOK.md`. Serve director mode with
`demo-director`, record
`http://127.0.0.1:8788/director-record.html?duration=120&autoplay=1`, keep the
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
- [x] Operator finalizer, media QC, conservative tweet counting, and prepost
  state checks added.
- [x] HB2 replay, director, submission draft, release audit, and focused tests
  passed where the local native-Windows environment could exercise them.
- [x] Full native HB2 unittest suite passed.
- [x] Full Linux/Nix test suite passes for rc10.
- [x] Nix flake check passes for rc10.
- [ ] Complete sponsor-integrated live run captured.
