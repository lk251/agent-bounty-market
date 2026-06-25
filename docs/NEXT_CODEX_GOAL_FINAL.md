# Next Codex Goal — Final Judge Evidence Upgrade and Operator Submission Finalizer

This file is the sole entrypoint for the next autonomous Codex run.

## Repository

```text
/home/mares/repos/agent-bounty-market
```

Known-good fallback release:

```text
hackathon-mixed-rc8
```

Canonical coordinator:

```text
https://github.com/lk251/agent-bounty-market/issues/28
```

Detailed work issues:

```text
#26 — judge-facing evidence and presentation correctness
#27 — operator finalizer, video QC, exact social copy, and final immutable RC
```

## Goal

Execute issue #26 and then issue #27 completely, without waiting for another prompt.

Read issue #28 first. Then read issue #26 in full and execute it as the current goal. When #26 is genuinely complete, post its required handoff, pull main, read issue #27 in full, and execute it. Each issue's completion gate is authoritative.

Do not stop after writing adapters or tests. Finish all unblocked work, run the complete gates, produce the final release handoff, and freeze code after the replacement RC is validated.

## Start

```bash
cd /home/mares/repos/agent-bounty-market
git status --short --branch
git log --oneline --decorate -20
git remote -v
git pull --ff-only
```

Read before editing:

```text
submission/FINAL_HANDOFF.md
submission/RELEASE_MANIFEST.json
submission/RELEASE_CHECKLIST.md
submission/RECORDING_RUNBOOK.md
submission/VOICEOVER_FINAL.md
submission/TWEET.md
submission/TYPEFORM_FINAL.md
submission/SUBMISSION_PORTAL_CHECKLIST.md
docs/SECURITY_AUDIT.md
GitHub issues #26, #27, and #28
```

Preserve `hackathon-mixed-rc8` and all earlier tags. Never rewrite or move them.

## Why the final pass is required

The current RC8 is technically valid, but its judge-facing director has four concrete defects:

```text
raw minor units shown as 2500 USD / 2000 USD / 500 USD instead of $25 / $20 / $5
synthetic https://github.test/... URL visible in the compounding scene
raw internal labels such as agent_declined and JSON arrays shown to judges
the strongest baseline -> intermediate -> final verifier proof and issue #21 dogfood proof are missing
```

The current Tweet Variant A also uses a short placeholder in a 275-character draft; replacing it with a real URL may exceed the X post limit.

Issue #26 fixes the evidence and presentation. Issue #27 makes final media/social/portal completion safe and local.

## Continuous execution protocol

For each issue:

1. Inspect current source, bundle, director assets, and release metadata before editing.
2. Use the dedicated branch/worktree required by issue #26.
3. Generate all judge-facing claims from protected evidence fragments, not hardcoded prose.
4. Add deterministic tests before broadening.
5. Commit focused, reviewable increments.
6. Push normally to the dedicated branch or `origin/main`; never force-push.
7. Run issue-specific validation plus the recurring full gate below.
8. Add the required issue handoff comment with commits, evidence digests, compact safe output, truth status, tests, blockers, and next issue.
9. Close only when the completion gate is genuinely met; otherwise leave open as partial with one exact blocker and continue.
10. Pull and proceed to the next issue without waiting for another prompt.

Do not ask for confirmation for ordinary safe engineering choices. Stop only at a real credential, safety, or irreversible external-operation boundary.

## Hard constraints

- Preserve `Mixed real/fallback` unless authenticated evidence genuinely upgrades a row.
- Never fabricate metrics, GitHub/Stripe objects, URLs, runtime evidence, receipts, or outcomes.
- No `.test` URL may remain in any judge-facing committed asset.
- Never display integer minor units as whole dollars/euros.
- Keep recorded-real Stripe full-transfer evidence separate from the deterministic split-settlement run.
- Candidate-controlled code, tests, workflows, or JSON cannot authorize settlement.
- Never expose or commit credentials, tokens, webhook secrets, private prompts, hidden tests, personal Motoko data, operator personal data, or video files.
- Do not merge/deploy Motoko or mutate Motoko master.
- Preserve the working RC8 recording path until the replacement passes every gate.
- Do not add broad product features.

## Issue #26 required result

The replacement winning bundle/director must show:

```text
real Motoko defect with evidence-backed before/after
project policy selects the measurable task and declines three unsuitable tasks in plain language
two mismatched solvers decline; Python terminal specialist claims
baseline rejected; idle-only candidate rejected; final background-study fix accepted
Reward $25.00; simulated split external allocation $20.00; retained internal credit $5.00
prior recorded-real Stripe transfer shown as a separate transaction
real GitHub issue #21 dogfood proof with exact candidate, receipt, verifier digest, and retained-credit replay evidence
compact truth matrix, not a wall of blocker text
```

No raw `agent_declined` labels, JSON arrays, `github.test` links, or unsupported metrics.

## Issue #27 required result

Provide a local ignored operator workflow:

```text
.demo/operator-submission.json
submission-finalize
video-check
submission-check --entry --prepost --state ...
submission-check --entry --final --state ...
```

It must:

- conservatively count real URLs in X/Twitter posts;
- rewrite unsafe tweet variants;
- validate actual MP4 duration/codec/resolution/audio with ffprobe when available;
- generate copy-ready local tweet/Discord/Typeform/portal files;
- keep team/contact/video/tweet/confirmation values out of Git;
- let final mode pass after the operator fills real values, without another code change.

## Recurring validation

At every issue boundary run at least:

```bash
nix develop --command python3 -m agent_bounty demo-build-winning-run \
  --db .demo/winning-run.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency \
  --bundle demo/bundles/winning-run

nix develop --command python3 -m agent_bounty demo-director \
  --bundle demo/bundles/winning-run \
  --host 127.0.0.1 \
  --port 8788 \
  --duration 120 \
  --check

nix develop --command python3 -m agent_bounty submission-check
nix develop --command python3 -m agent_bounty submission-check --entry
nix develop --command python3 -m agent_bounty security-audit --quick
nix develop --command python3 -m agent_bounty demo-rehearse \
  --mode replay \
  --bundle demo/bundles/winning-run \
  --repeat 5

nix develop --command python3 -m unittest discover -s tests
nix flake check
git diff --check
git status --short --branch
```

After issue #27 also run:

```bash
nix develop --command python3 -m agent_bounty security-audit --full
```

Run prepost finalizer checks using safe synthetic operator state. Run fresh-clone validation from GitHub at the final tag.

## Release policy

- RC8 remains the fallback release throughout development.
- Do not tag intermediate work.
- After both #26 and #27 pass every gate, create one new immutable **annotated** RC through release provenance v2.
- Preserve RC1–RC8.
- Actual operator state, video metadata, final tweet URL, and submission confirmations remain ignored local data and must not require another tag.
- Update the final handoff, release manifest/checklist, recording runbook, voiceover, entry package, and coordinator comment.

## Final handoff

Comment on issue #28 with:

```text
final annotated tag, tag object, and target commit
status of #26 and #27
Motoko verification fragment digest plus baseline/intermediate/final verdicts and metrics
issue #21 dogfood fragment digest, candidate, receipt, verifier digest, and replay evidence
correct displayed reward/external/retained amounts
proof no .test URL or raw internal labels remain in judge-facing assets
bundle, attestation, truth-matrix, release-manifest, and tag-provenance digests
security quick/full results
video-check and submission-finalize sample outputs
standard, draft, and prepost submission-check results
remaining operator-only fields
five-run rehearsal timing
fresh-clone result
exact director, recording, prepost, and final submission commands
```

Then freeze code. The operator's remaining work should be only:

```text
record the video
fill local operator state
run video/prepost checks
post tweet/video with @NousResearch
fill final tweet URL
post Discord submission
submit Typeform
fill confirmation paths
run final checker
retain backups and confirmations
```
