# Next Codex Goal — Final Dogfood, Audit, Entry Compliance, and Recording Freeze

This file is the single entrypoint for the next autonomous Codex run.

## Repository

```text
/home/mares/repos/agent-bounty-market
```

Current known-good release candidate:

```text
hackathon-mixed-rc6
```

Canonical queue coordinator:

```text
https://github.com/lk251/agent-bounty-market/issues/25
```

Detailed queue file:

```text
docs/codex-final-dogfood-queue.md
```

## Goal

Work continuously through the following issues in order, without waiting for another prompt:

1. **Issue #21** — fund and solve the release-provenance defect as a real second bounty using retained operating credit;
2. **Issue #22** — independently adversarially audit the money, verification, webhook, fragment, execution, and release trust boundaries;
3. **Issue #23** — complete the required tweet, Discord, Typeform, video-metadata, and entry-consistency package;
4. **Issue #24** — build the optional bundle-backed presentation director mode, but cut this first if time is constrained.

Read issue #25 first, then read each numbered issue in full immediately before executing it. Each issue's completion gate is authoritative.

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
submission/TWEET.md
submission/JUDGE_QA.md
docs/codex-final-dogfood-queue.md
GitHub issues #21, #22, #23, #24, and #25
```

Preserve all legitimate work and all prior release tags. Never reset, discard, force-push, rewrite tag history, merge/deploy Motoko, or mutate Motoko master.

## Continuous execution protocol

For each issue:

1. Inspect the current implementation and repository state before editing.
2. Establish the smallest correct vertical slice.
3. Add deterministic tests before broadening the change.
4. Use the dedicated bounty branch/worktree required by issue #21.
5. Keep candidate-controlled code separate from the protected verifier and settlement authority.
6. Commit focused, reviewable increments.
7. Push normally to the appropriate branch or `origin/main`; never force-push.
8. Run issue-specific validation plus the recurring full gate below.
9. Add the required GitHub issue handoff comment with commits, commands, compact safe output, truth status, blockers, and next issue.
10. Close the issue only when its completion gate is genuinely met; otherwise leave it open as partial with one exact blocker and continue.
11. Pull and proceed to the next issue without waiting for another prompt.

Do not ask for confirmation for ordinary safe engineering choices. Stop only for a genuine credential, safety, or irreversible-operation boundary.

## Priority and cut policy

Preserve in this order:

1. **Issue #21:** authentic second-bounty dogfooding and release-provenance correctness;
2. **Issue #22:** security/correctness audit and all confirmed P0/P1 fixes;
3. **Issue #23:** entry compliance, required `@NousResearch` tweet copy, Discord/Typeform package, and final claim consistency;
4. **Issue #24:** presentation director mode.

If time is constrained, cut issue #24 first. Do not trade release integrity, security, or required submission mechanics for visual polish.

## Hard constraints

- Preserve the `Mixed real/fallback` truth boundary unless authenticated evidence genuinely upgrades a component.
- Never fabricate Hermes, NVIDIA, OpenShell, GitHub, or Stripe runtime/object evidence.
- Never expose credentials, API keys, webhook secrets, tokens, Checkout URLs with client state, private prompts, hidden tests, personal Motoko state, or Hermes session data.
- Never overwrite RC1–RC6 tags.
- Do not create a new release tag until release provenance, security audit, submission checks, full tests, Nix checks, fresh-clone rehearsal, and five-run replay all pass.
- No manual SQLite edits in any claimed workflow.
- Candidate-controlled tests, workflows, JSON, or code cannot authorize payment.
- Do not add broad marketplace features after issue #24.

## Recurring validation

At every issue boundary run at least:

```bash
nix develop --command python3 -m agent_bounty demo-build-winning-run \
  --db .demo/winning-run.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency \
  --bundle demo/bundles/winning-run

nix develop --command python3 -m agent_bounty submission-check
nix develop --command python3 -m agent_bounty release-audit

nix develop --command python3 -m agent_bounty demo-rehearse \
  --mode replay \
  --bundle demo/bundles/winning-run \
  --repeat 5

nix develop --command python3 -m unittest discover -s tests
nix flake check
git diff --check
git status --short --branch
```

After issue #22, also run:

```bash
nix develop --command python3 -m agent_bounty security-audit --quick
nix develop --command python3 -m agent_bounty security-audit --full
```

After issue #23, also run:

```bash
nix develop --command python3 -m agent_bounty submission-check --entry
```

`submission-check --entry --final` may fail only because genuine operator placeholders such as the final video/tweet URL are still unfilled. Record those exact placeholders; never invent final URLs.

## Progress ledger

Continue updating:

```text
docs/autonomous-progress.md
```

For each issue record:

```text
UTC start/end
commits and branches
features/fixes completed
bounty contract/receipt/economic evidence where relevant
security findings and release recommendation
submission-check status and placeholders
bundle/release digests
test counts
blockers
next issue
```

Do not include secrets or private data.

## Final handoff

After issue #24, or after explicitly cutting it:

1. update `submission/FINAL_HANDOFF.md`;
2. update `submission/RECORDING_RUNBOOK.md`;
3. update the release manifest/checklist using the provenance mechanism from issue #21;
4. preserve all prior tags;
5. create a new immutable **annotated** RC tag only if every gate passes;
6. run fresh-clone validation from GitHub;
7. record the final bundle, attestation, truth-matrix, and tag-provenance digests;
8. stop feature development and leave only emergency recording/submission fixes.

Comment on issue #25 with:

```text
final tag and commit
status of issues #21-#24
second-bounty contract/receipt/economic evidence
security-audit recommendation and P0/P1 fixes
submission-check --entry result and remaining operator placeholders
bundle/attestation/truth-matrix/provenance digests
five-run rehearsal timing
fresh-clone result
exact recording/director command
remaining operator actions before tweet, Discord, and Typeform submission
```
