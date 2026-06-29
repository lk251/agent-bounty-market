# Next Codex Goal — Final publication freeze after issue #29

Execute this goal completely on HB3/NixOS.

## Repository

Work in:

```bash
/home/mares/repos/agent-bounty-market
```

## Purpose

Issue #29 produced a much stronger story/flywheel release, but the branch/tag state and publication docs still need a final hygiene pass before recording/submission.

Do not add product features. This is a publication-freeze task: make the final release internally consistent, judge-facing, and safe to record.

## Starting point

Use branch:

```bash
codex/issue-29-story-flywheel
```

Known issue #29 final commit:

```text
17b284e31534e3ae765eaf009e9f8885f63678c7
```

Known tag:

```text
hackathon-mixed-rc10
```

## Required work

### 1. Confirm state

Verify:

- branch `codex/issue-29-story-flywheel` exists locally and remotely;
- commit `17b284e31534e3ae765eaf009e9f8885f63678c7` exists;
- annotated tag `hackathon-mixed-rc10` exists and targets that commit;
- GitHub issue #29 is closed with the completion comment;
- `release-audit --tag hackathon-mixed-rc10` passes before making changes.

### 2. Fix stale final handoff text

Update `submission/FINAL_HANDOFF.md` so it no longer says issue #29 is unfinished.

It must say clearly:

- issue #29 is complete;
- completion comment exists;
- `hackathon-mixed-rc10` was created and audited;
- release remains `Mixed real/fallback`;
- settlement shown on screen is:
  - `$25.00` reward;
  - `$20.00` solver wallet operating credit;
  - `$5.00` human/operator payout through the Stripe settlement path.

Remove or rewrite all stale phrases such as:

- `No completion comment has been posted yet`;
- `issue #29 should not be closed`;
- `Remaining issue #29 closeout`;
- `Create the immutable annotated hackathon-mixed-rc10 tag`.

### 3. Advance main or document exact blocker

The plain repository URL should show the final story, not RC9-era docs.

Fast-forward or merge `main` to the final release commit if safe.

If `main` cannot be advanced safely, record the exact blocker and ensure all submission copy uses the `hackathon-mixed-rc10` tag/release URL instead of the plain repo URL.

### 4. Final judge-facing copy polish

In generated director/dashboard/submission assets, remove or improve remaining internal/debug wording.

Specifically, judge-facing assets must not contain:

```text
not funded: Not funded
background_study
Transfer provider: fake
solver_python_terminal_tui
```

Preferred replacements:

- `not funded: Not funded...` -> `Not funded: vague, subjective, or missing verifier`;
- `background_study` -> `background study`;
- `Transfer provider: fake` -> `Settlement mode: deterministic fallback`;
- `solver_python_terminal_tui` -> `Python terminal/TUI specialist`.

Preserve the `Mixed real/fallback` truth badge and do not fabricate live Stripe, Hermes, NVIDIA, OpenShell, or GitHub execution.

### 5. Rebuild and validate

Rebuild the bundle and director assets.

Run:

```bash
nix develop --command python3 -m unittest discover -s tests
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
nix develop --command python3 -m agent_bounty demo-rehearse \
  --mode replay \
  --bundle demo/bundles/winning-run \
  --repeat 5
nix develop --command python3 -m agent_bounty submission-check --entry --prepost
nix flake check
git diff --check
```

If `submission-check --entry --prepost` needs operator-local `.demo/operator-submission.json`, do all code-side checks possible and report the exact operator-state blocker. Do not fabricate a pass.

### 6. Tag policy

If any committed file changes, create a new immutable annotated tag:

```text
hackathon-mixed-rc11
```

Do not mutate or delete `hackathon-mixed-rc10`.

If you create RC11:

- update release docs from RC10 to RC11 where appropriate;
- render the canonical tag message with the project command;
- create the annotated tag;
- run `release-audit --tag hackathon-mixed-rc11`.

### 7. Push and handoff

Push:

- final branch;
- updated `main` if advanced;
- new tag if created.

Final handoff must include:

- final commit SHA;
- final tag;
- whether `main` now points to the final release;
- release-audit result;
- whether stale handoff text was removed;
- proof that judge-facing copy no longer contains:
  - `not funded: Not funded`;
  - `background_study`;
  - `Transfer provider: fake`;
  - `solver_python_terminal_tui`;
- exact recording URL;
- Windows static-server fallback instructions.

## Completion gate

This goal is complete only when:

- final release docs no longer contradict issue #29 closure;
- final judge-facing assets are polished;
- release audit passes for the final tag;
- `main` is either advanced to final release or the blocker is explicit and submission copy uses the tag URL;
- handoff gives exact recording instructions.
