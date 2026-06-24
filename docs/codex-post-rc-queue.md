# Codex Post-RC Queue

Canonical coordinator: <https://github.com/lk251/agent-bounty-market/issues/20>

Current release candidate: `hackathon-mixed-rc1`.

Execute in order:

1. <https://github.com/lk251/agent-bounty-market/issues/15> — recording QA and dashboard polish
2. <https://github.com/lk251/agent-bounty-market/issues/16> — authenticated fragment importers
3. <https://github.com/lk251/agent-bounty-market/issues/17> — live setup wizard and operator runbooks
4. <https://github.com/lk251/agent-bounty-market/issues/18> — submission red-team and judge Q&A
5. <https://github.com/lk251/agent-bounty-market/issues/19> — fresh-clone release integrity and final handoff

## Instruction for Codex

Read issue #20 first, then issue #15 in full and execute it as the current goal. At every issue boundary:

- preserve the `Mixed real/fallback` truth boundary unless real evidence genuinely upgrades it;
- add tests for any new behavior;
- rebuild and rehearse `demo/bundles/winning-run` five times;
- push focused commits normally to `origin/main`;
- add the required handoff comment;
- close only if the issue completion gate is truly satisfied;
- pull `main` and continue to the next issue without waiting for another prompt.

Do not fabricate real sponsor integrations, hide blockers, commit secrets, mutate Motoko master, or add broad marketplace features. The goal is to make the current truthful mixed release candidate clearer, safer, easier to upgrade with real fragments, and submission-ready.
