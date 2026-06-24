# Codex Live Integration Queue

Canonical coordinator: <https://github.com/lk251/agent-bounty-market/issues/13>

Execute in order:

1. <https://github.com/lk251/agent-bounty-market/issues/8> — real Hermes Agent + NVIDIA Nemotron
2. <https://github.com/lk251/agent-bounty-market/issues/9> — real NVIDIA OpenShell / NemoClaw
3. <https://github.com/lk251/agent-bounty-market/issues/10> — real GitHub issue / claim / PR / receipt lifecycle
4. <https://github.com/lk251/agent-bounty-market/issues/11> — real split Stripe settlement and retained-credit spend
5. <https://github.com/lk251/agent-bounty-market/issues/12> — authenticated recorded-real bundle, rehearsal, and submission freeze

## Goal instruction

Read issue #13 first, then issue #8 in full and execute it as the current goal. At each issue boundary:

- add the required handoff comment;
- close only when the completion gate is genuinely satisfied;
- otherwise leave it open as partial with one exact external blocker;
- pull `main` and continue to the next issue without waiting for another prompt.

Never fabricate a model/runtime, OpenShell run, GitHub/Stripe object, credential, or live success. Keep all credentials in the trusted local environment and out of commits, prompts, traces, candidate workspaces, sandbox images, issue comments, and bundles.

Inspect remote install scripts before execution, prefer user-owned installs, and do not use sudo or modify system/NixOS services without explicit operator authorization.

At every boundary run:

```bash
nix develop --command python3 -m compileall agent_bounty tests verifiers
nix develop --command python3 -m unittest discover -s tests
nix flake check
git diff --check
git status --short --branch
```

Continue `docs/autonomous-progress.md`. After issue #12, update `submission/FINAL_HANDOFF.md`, create `submission/RECORDING_RUNBOOK.md`, push a truthfully named immutable release candidate, and comment on issue #13 with the final truth matrix, bundle digest, rehearsal timing, blockers, and recording command.
