# Next Codex Goal — Final story and flywheel pass

Execute GitHub issue #29 completely:

https://github.com/lk251/agent-bounty-market/issues/29

## Context

This is the final messaging/product-presentation pass before recording. The code is already functionally strong, but the current demo copy undersells the idea and contains confusing internal language.

The winning story is:

> A project agent spends from a project budget to buy verified software work. A specialist solver agent earns the bounty. The solver wallet keeps most of the reward as operating credit and sends a smaller payout to the human/operator account through the Stripe settlement path. Each accepted/declined/paid trajectory becomes high-quality data for training future orchestrators.

Do not add broad product features. This is a focused presentation/economics/code-generation pass.

## Required work

1. Read issue #29 in full.
2. Reverse the deterministic split in the demo:
   - reward: `$25.00`
   - solver wallet operating credit: `$20.00`
   - human/operator payout through Stripe settlement path: `$5.00`
3. Ensure the bounty issuer is not described as controlling the solver's post-acceptance split.
4. Remove or reword judge-facing `idle-only` language.
5. Replace judge-facing `Reward exceeds maximum bounty amount` and `Minimum remaining reserve would be violated` with clear project-budget language.
6. Replace `Policy and budget select one bounded bounty while alternatives can decline` with clear language.
7. Add the agent-labor-market-to-orchestrator-training-data flywheel to:
   - director scenes and notes;
   - `submission/DEMO_SCRIPT.md`;
   - `submission/JUDGE_QA.md`;
   - submission writeup / tweet variants where appropriate;
   - generated `demo/bundles/winning-run/*` assets.
8. Preserve the `Mixed real/fallback` truth boundary and do not fabricate live Stripe/Hermes/NVIDIA/GitHub execution.
9. Rebuild the winning bundle, director assets, and any release/submission files affected by the changes.
10. Run the full relevant validation listed in issue #29.

## New narration target

Use this script as the target:

```text
0:00–0:15 — Problem

Open-source projects have endless useful work, but no native market where project agents can buy verified fixes and specialist agents can earn from them.

0:15–0:35 — Project spends

My Motoko project has a real bug: typing froze while background evidence-store work was running. The project agent uses its budget to fund a $25 bounty, but only because the task has a protected verifier.

0:35–0:55 — Agents choose

Specialist agents inspect the bounty. The frontend and CUDA agents decline because it is outside their verified skill set. The Python terminal/TUI specialist claims it because the task matches its history and margin.

0:55–1:20 — Verification

The project does not trust the solver's claim. Its verifier tests three versions: the original buggy version, a superficial typing fix, and the final background-study fix. The first two fail. Only the real fix passes, so payment depends on evidence, not persuasion.

1:20–1:40 — Settlement

The solver earns the $25 bounty. Its wallet keeps $20 as operating credit for tools, API calls, compute, or future bounties, and sends $5 through the Stripe settlement path to the operator account. The split is recorded exactly once.

1:40–2:05 — Flywheel

That operating credit funds the next useful issue. And the market produces more than software: every claim, decline, patch, verifier result, payout, and spend becomes high-quality training data for future orchestrators that learn which specialist agents to call.

2:05–2:15 — Close

Agent Bounty Market turns open-source maintenance into a verified agent labor market — and a data engine for better agent orchestration.
```

## Validation

Run at minimum:

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
```

If all release gates pass and you create a new immutable RC tag, state the tag clearly in the handoff. If not, state exactly what remains.

## Completion handoff

When done, comment on issue #29 with:

- commits pushed;
- whether a new RC tag was created;
- settlement split shown on screen;
- exact wording replacements made;
- proof that no judge-facing `idle-only`, `reward exceeds maximum bounty amount`, `minimum remaining reserve would be violated`, or `alternatives can decline` remains;
- validation commands and results;
- recording instructions if they changed.

Then close #29 only if the completion gate is actually satisfied.
