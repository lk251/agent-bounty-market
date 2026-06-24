# Codex Autonomous Execution Queue

Canonical coordinator: <https://github.com/lk251/agent-bounty-market/issues/6>

Execute these issues in order:

1. <https://github.com/lk251/agent-bounty-market/issues/1> — GitHub-native bounty event spine and contract protocol
2. <https://github.com/lk251/agent-bounty-market/issues/2> — Hermes project-agent buyer
3. <https://github.com/lk251/agent-bounty-market/issues/3> — specialized Hermes solver agents
4. <https://github.com/lk251/agent-bounty-market/issues/4> — real Stripe settlement and earn → retain → spend
5. <https://github.com/lk251/agent-bounty-market/issues/5> — presentation-grade demo and submission package

## Codex instruction

Read issue #6 first, then read issue #1 in full and execute it as your current goal. When an issue’s completion gate is reached, add the required handoff comment, close it, pull `main`, and continue to the next numbered issue without waiting for another prompt.

If a real external integration is unavailable, complete every unblocked implementation/test/runbook item, record one exact blocker in the issue, leave it open as partial, and continue. Never fabricate sponsor integration, model/runtime identity, Stripe/GitHub objects, or success.

Keep credentials in trusted local environment only. Never expose them to candidate repositories, Hermes prompts/traces, OpenShell workspaces, commits, issue comments, or demo bundles.

At every issue boundary run:

```bash
nix develop --command python3 -m compileall agent_bounty tests verifiers
nix develop --command python3 -m unittest discover -s tests
nix flake check
git diff --check
git status --short --branch
```

Maintain `docs/autonomous-progress.md`, push focused commits normally to `origin/main`, never force-push, never merge/deploy Motoko, and preserve one trustworthy end-to-end loop over optional features.

After issue #5, create `submission/FINAL_HANDOFF.md` and comment on issue #6 with the release/tag, status of issues #1–#5, exact rehearsal command, run mode, bundle digest, test results, blockers, and recording instructions.
