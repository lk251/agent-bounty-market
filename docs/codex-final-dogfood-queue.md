# Codex Final Dogfood Queue

Canonical coordinator: <https://github.com/lk251/agent-bounty-market/issues/25>

Current release candidate: `hackathon-mixed-rc6`.

Execute in order:

1. <https://github.com/lk251/agent-bounty-market/issues/21> — fund and solve the release-provenance bug as a real second bounty
2. <https://github.com/lk251/agent-bounty-market/issues/22> — independent adversarial audit, model checking, mutation probes, and fuzzing
3. <https://github.com/lk251/agent-bounty-market/issues/23> — required tweet/Discord/Typeform/video entry package and claim consistency
4. <https://github.com/lk251/agent-bounty-market/issues/24> — optional bundle-backed presentation director mode

## Instruction for Codex

Read issue #25 first, then issue #21 in full and execute it as the current goal. At every boundary:

- use a dedicated bounty branch where issue #21 requires it;
- preserve prior release tags;
- keep the `Mixed real/fallback` truth boundary unless authenticated evidence genuinely upgrades it;
- add deterministic tests;
- rebuild and rehearse the winning bundle five times;
- run submission and release audits;
- push focused commits normally;
- add the required issue handoff comment;
- close only when the completion gate is truly satisfied;
- pull and continue to the next issue without waiting for another prompt.

Priority is #21, then #22, then #23. Cut #24 first if time is constrained. Never trade release integrity, security, or required entry compliance for optional visual polish.

Do not fabricate live integration, overwrite tags, expose secrets, mutate Motoko master, trust candidate-controlled verification, or manually edit SQLite for a claimed flow.

After the queue, update the final handoff and recording runbook, create a new immutable annotated release tag only if every gate passes, run fresh-clone validation, and stop feature development.
