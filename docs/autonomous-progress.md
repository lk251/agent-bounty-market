# Autonomous Progress

This ledger records Codex progress through the coordinator queue in
`docs/codex-autonomous-queue.md` and GitHub issue #6.

## Issue #1: GitHub Native Bounty Spine

Status: partial, external blocker for real GitHub credentials/webhook endpoint.

Implemented:

- schema v7 durable GitHub tables for repositories, operations, webhook
  deliveries, issue contracts, pull requests, and result publications;
- `FakeGitHubClient` and `GitHubRestClient` behind a small client boundary;
- `github-status` with content-safe blocker reporting;
- digest-bound `agent-bounty-contract-v1`, `agent-bounty-claim-v1`, and
  `agent-bounty-submission-v1` markers;
- signed webhook recording with `X-Hub-Signature-256`, delivery idempotency,
  replay detection, repository scoping, and restart-safe processing;
- issue contract import, claim synchronization, pull request submission
  synchronization, stale SHA rejection, active-claimant checks, and
  candidate-owned CI non-authority;
- trusted verification result publication through a durable commit-status
  journal;
- explicit claim expiry and reclaim support;
- local fake-GitHub Motoko lifecycle demo using the real protected verifier.

Validation run:

```bash
nix develop --command python3 -m py_compile agent_bounty/github_integration.py agent_bounty/cli.py agent_bounty/core.py agent_bounty/db.py tests/test_github_integration.py
nix develop --command python3 -m unittest tests.test_github_integration
nix develop --command python3 -m agent_bounty demo-github-motoko --db "$tmpdir/github.sqlite3" --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
nix develop --command python3 -m unittest discover -s tests
```

Observed results:

- focused GitHub tests: 6 passed;
- fake GitHub Motoko demo: `ok=true`;
- full test suite: 67 passed, 2 skipped.

Exact real-integration blocker:

```text
github-status reports missing AGENT_BOUNTY_GITHUB_INTEGRATION=1,
AGENT_BOUNTY_GITHUB_TOKEN or GH_TOKEN, AGENT_BOUNTY_GITHUB_REPOSITORY,
and AGENT_BOUNTY_GITHUB_WEBHOOK_SECRET.
```

Next boundary action:

- run the required full validation gate;
- commit and push the issue #1 implementation;
- post the partial handoff comment on issue #1;
- leave issue #1 open until real GitHub credentials and webhook delivery are
  available;
- pull `main`, then continue issue #2.

## Issue #2: Hermes Project-Agent Buyer

Status: implementation in progress; real Hermes/NemoClaw/Nemotron execution is
externally blocked unless the runtime and reviewed wrapper command are provided.

Implemented so far:

- inspected current Hermes Agent, Hermes Skills System, NVIDIA NemoClaw,
  NVIDIA NemoClaw GitHub, and NVIDIA Nemotron sources;
- schema v8 project-agent tables for skills, policies, candidates, runs, and
  decisions;
- deterministic `fake-project-agent-runtime-v1`;
- gated `hermes-cli-adapter-v1` with exact blocker/status reporting;
- versioned skills under `skills/project-agent/`;
- trusted `project-agent-policy-v1` checks for repo/class/verifier/currency,
  reward ceiling, human threshold, reserve floor, simultaneous bounties, and
  contract completeness;
- candidate queue for the four required Motoko demo cases;
- scan/evaluate/fund-and-publish CLI commands;
- `demo-project-agent-motoko`;
- deterministic tests for malformed output, prompt injection, policy isolation,
  decline paths, exactly-once publish, publication failure recovery, restart
  replay, and Hermes blocker reporting.

Validation run so far:

```bash
nix develop --command python3 -m py_compile agent_bounty/project_agent.py agent_bounty/cli.py agent_bounty/db.py
nix develop --command python3 -m agent_bounty project-agent status
nix develop --command python3 -m agent_bounty demo-project-agent-motoko --db "$tmpdir/project-agent.sqlite3"
nix develop --command python3 -m unittest tests.test_project_agent
```

Observed results:

- project-agent status: fake runtime available, Hermes blocked by missing CLI,
  run env, and reviewed wrapper command;
- project-agent Motoko demo: `ok=true`;
- focused project-agent tests: 9 passed.

Current external blocker:

```text
No real Hermes/NemoClaw/Nemotron runtime is configured. project-agent status
requires AGENT_BOUNTY_RUN_HERMES_PROJECT_AGENT=1,
AGENT_BOUNTY_HERMES_EVALUATE_COMMAND, and an installed Hermes CLI or
AGENT_BOUNTY_HERMES_CLI.
```

## Issue #3: Specialized Solver Agents

Status: implementation in progress; real Hermes/OpenShell/NemoClaw live solve is
externally blocked, deterministic Motoko replay path is implemented.

Implemented so far:

- schema v9 solver-agent tables for profiles, skills, evaluations, executions,
  submissions, and capability events;
- four versioned solver skills under `skills/solver-agent/`;
- three durable demo profiles: Python terminal/TUI, TypeScript/frontend, and
  CUDA/PyTorch performance;
- fake solver runtime with truthful model/runtime identity;
- solver decision schema validation;
- trusted claim policy for open contracts, repo/class allowlists, operating
  budget, margin, canonical reward, and active lease;
- lease-generation claim idempotency for expiry/reclaim;
- deterministic Motoko issue #1 replay execution;
- PR evidence package with contract digest, solver profile, base/candidate SHA,
  changed files, commands, safe output digest, limitations, estimated cost, and
  verification receipt;
- protected verifier submission path;
- capability/economic update exactly once after accepted verification;
- rejected capability path with no earnings;
- live-local-fallback record that is clearly blocked/not a real live solve;
- solver-agent status, register, discover, evaluate, claim, execute, submit, and
  demo commands;
- deterministic tests for malformed output, capability mismatch, negative
  margin, budget, claim replay/race, lease expiry/reclaim, path policy, PR-head
  binding, credential trace safety, deterministic replay, rejection accounting,
  skill promotion gating, runtime blockers, live fallback, and full demo.

Validation run so far:

```bash
nix develop --command python3 -m py_compile agent_bounty/solver_agent.py agent_bounty/cli.py agent_bounty/db.py
nix develop --command python3 -m agent_bounty solver-agent status
nix develop --command python3 -m agent_bounty demo-solver-motoko --db "$tmpdir/solver.sqlite3" --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
nix develop --command python3 -m unittest tests.test_solver_agent
```

Observed results:

- solver-agent status: fake runtime available; Hermes and OpenShell/NemoClaw
  blocked;
- solver demo: `ok=true`;
- focused solver tests: 11 passed.

Current external blockers:

```text
No real Hermes solver wrapper, no configured OpenShell/NemoClaw backend, and no
reviewed safe live issue for a real live solve.
```

## Issue #4: Real Stripe Settlement and Earn -> Retain -> Spend

Status: implementation in progress; deterministic split-retain-spend loop is
implemented. Real prior Stripe sandbox evidence exists for full-transfer
settlement, but a real split-Stripe-transfer adapter is not claimed by the new
economic-loop command.

Implemented so far:

- schema v10 settlement and operating-credit tables:
  `settlement_policies`, `settlement_allocations`,
  `solver_operating_policies`, and `solver_operating_spends`;
- solver operating ledger accounts for available, reserved, and spent operating
  credit;
- explicit settlement policy with exact reward split, operator retention
  consent, and full-external-transfer default when no retention is authorized;
- split allocation from accepted reward to external payout, retained operating
  credit, and optional platform fee;
- external portion creates the only payout/transfer record;
- retained credit is tracked as internal operating balance, not an AI bank
  account;
- retained-credit spend policy for allowlisted project, repo, issue class,
  verifier, currency, amount, human threshold, and balance;
- retained-credit spend into a second digest-bound fake-GitHub bounty contract;
- retry/replay/reversal handling for deterministic split transfers;
- `economic-loop status`, `economic-loop allocate`,
  `economic-loop spend-retained`, and `demo-economic-loop` commands;
- `docs/economic-loop.md` plus README, architecture, threat-model, and Stripe
  runbook updates.

Validation run so far:

```bash
nix develop --command python3 -m py_compile agent_bounty/economic_loop.py agent_bounty/cli.py agent_bounty/db.py tests/test_economic_loop.py
nix develop --command python3 -m unittest tests.test_economic_loop
nix develop --command python3 -m agent_bounty demo-economic-loop --db "$tmpdir/economic.sqlite3" --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
```

Observed results:

- focused economic-loop tests: 9 passed;
- deterministic `demo-economic-loop`: `ok=true`;
- allocation split: 2500 reward -> 2000 fake external transfer + 500 retained
  operating credit + 0 platform fee;
- retained-credit spend: 500 funds second fake-GitHub bounty contract;
- replay of allocation and spend returns replayed rows without duplicate
  ledger movement.

Current external blocker:

```text
No reviewed real split Stripe Connect Transfer adapter is implemented. The
existing safe real sandbox evidence in docs/chatgpt-pro-stripe-blocker-report.md
covers a full-transfer Stripe loop, while demo-economic-loop truthfully runs
the split-retain-spend path with deterministic fake external transfer IDs.
```

## Issue #5: Presentation Demo and Submission Package

Status: implementation in progress; dependency-free local/replay presentation
harness and submission packet are implemented. Full live sponsor-integrated run
is externally blocked by missing real GitHub/Hermes/OpenShell configuration and
the missing real split-transfer adapter.

Implemented so far:

- `demo-preflight --mode local|replay|live` with safe status reporting for repo,
  Motoko fixture, schema, GitHub, Stripe, project-agent, solver-agent,
  OpenShell, ports, runtime, and secret-file checks;
- `demo-local` and `demo-rehearse --mode local` running the deterministic
  end-to-end economic loop from fresh state;
- sanitized bundle capture with `manifest.json`, `bundle.json`, and
  event-backed `dashboard.html`;
- `demo-replay` and `demo-rehearse --mode replay` bundle validation with digest
  checks and fake/live truth checks;
- `demo-live` honest refusal until live prerequisites are configured;
- `demo-reset --yes` that deletes only `.demo` state;
- static dashboard rendering project, agent decision, trust/economics, and
  compounding cards from persisted records;
- `docs/demo-presentation.md`;
- submission packet: `DEMO_SCRIPT.md`, `SHOT_LIST.md`, `SUBMISSION.md`,
  `TWEET.md`, `FORM_ANSWERS.md`, `LIMITATIONS.md`, and `ARCHITECTURE.mmd`;
- placeholder `demo/bundles/winning-run/README.md` for the future
  authenticated recorded-real bundle.

Validation run so far:

```bash
nix develop --command python3 -m py_compile agent_bounty/demo_presentation.py agent_bounty/cli.py
nix develop --command python3 -m unittest tests.test_demo_presentation
nix develop --command python3 -m agent_bounty demo-preflight --mode local
nix develop --command python3 -m agent_bounty demo-rehearse --mode local --db "$tmpdir/local.sqlite3" --bundle "$tmpdir/bundle" --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
nix develop --command python3 -m agent_bounty demo-rehearse --mode replay --bundle "$tmpdir/bundle"
nix develop --command python3 -m unittest discover -s tests
nix flake check
git diff --check --cached
git diff --check
```

Observed results:

- focused demo presentation tests: 5 passed;
- local preflight: `ok=true`;
- local rehearsal: `ok=true`, about 15.7 seconds in this run;
- replay rehearsal: `ok=true`.
- full test suite: 101 passed, 2 skipped;
- `nix flake check`: all checks passed.

Current external blockers:

```text
No real GitHub credentials/webhook, no real Hermes project/solver wrapper, no
OpenShell/NemoClaw backend, and no reviewed real split Stripe Connect Transfer
adapter are configured. The current presentation can truthfully demonstrate the
complete local loop and replay validated local bundles, but not claim a full
live sponsor-integrated run.
```

## Issue #8: Real Hermes Agent + NVIDIA Nemotron Decisions

UTC start: 2026-06-24T15:03:00Z
UTC validation: 2026-06-24T15:41:21Z

Status: partial, external blocker for real NVIDIA/Nemotron credentials/model
discovery.

Implemented:

- inspected issue #13, issue #8, the live integration queue, project/solver
  docs, architecture, threat model, and the official Hermes/NVIDIA/NemoClaw
  sources named by the issue;
- downloaded and inspected the official Hermes installer before execution;
- attempted the documented user-owned Hermes install with setup/browser/bundled
  skills disabled, then completed it through a Nix-provided `uv`, `python3.11`,
  and `nodejs_22` path after the direct generic-Linux binary path failed on
  NixOS;
- added `agent_bounty.hermes_integration` with safe Hermes/NVIDIA/Nemotron
  status reporting, installer evidence, model-discovery gating, skill manifests,
  idempotent skill installation, JSON-only project/solver wrapper entrypoints,
  skill-value fixture reporting, and a sanitized Hermes decision demo bundle;
- added role-specific wrapper envs:
  `AGENT_BOUNTY_HERMES_PROJECT_EVALUATE_COMMAND` and
  `AGENT_BOUNTY_HERMES_SOLVER_EVALUATE_COMMAND`;
- added a real solver Hermes runtime boundary alongside the existing project
  Hermes runtime boundary;
- added CLI commands:
  `hermes-status`, `hermes-install-skills`, `hermes-skill-eval`,
  `hermes-project-wrapper`, `hermes-solver-wrapper`, and
  `demo-hermes-decisions`;
- installed the project-owned skills idempotently under
  `/home/mares/.hermes/skills/agent-bounty-market`;
- verified Hermes CLI:
  `Hermes Agent v0.17.0 (2026.6.19) · upstream 9259d1e5`;
- added deterministic wrapper tests proving separate project and solver wrapper
  commands can drive decisions while trusted policy remains authoritative;
- added `uv`, `python311`, and `nodejs_22` to the dev shell so the NixOS Hermes
  installer path is reproducible without sudo or system service changes;
- documented the live Hermes boundary in `docs/hermes-live-integration.md`.

Safe evidence:

```text
official installer digest observed:
sha256:975e525aa420db1ec49b1ba0d6012682edf68224322656a68b87b17655bc38a2

skill manifest digest:
sha256:7ad94bab5915df4b14223a5adad54b7c867461830a4c9998443f836c71a89ff1

installed skill manifest digest:
sha256:ac4dba10fc228b886ad88b3a2796fe9665264ea1fbde641efb7d8822f72b7cbe

fallback demo bundle digest:
sha256:0f6dc3a99635306fb34b2657009c3a7503ac9cf4727dca4d31e629f5e96e0e0b
```

Exact external blocker:

```text
NVIDIA_API_KEY is not present. Without it, `hermes-status --discover-models`
cannot query NVIDIA NIM `/v1/models`, cannot discover a real Nemotron model ID,
and cannot perform a real Nemotron-backed Hermes project/solver decision run.
```

Validation run:

```bash
nix develop --command python3 -m py_compile agent_bounty/hermes_integration.py agent_bounty/project_agent.py agent_bounty/solver_agent.py
nix develop --command python3 -m unittest tests.test_project_agent
nix develop --command python3 -m unittest tests.test_solver_agent
nix develop --command python3 -m unittest tests.test_hermes_integration
nix develop --command python3 -m compileall agent_bounty tests verifiers
nix develop --command python3 -m unittest discover -s tests
nix flake check
git diff --check --cached
git diff --check
```

Observed results:

- project-agent tests: 9 passed;
- solver-agent tests: 11 passed;
- Hermes integration tests: 4 passed;
- full test suite: 105 passed, 2 skipped;
- `nix flake check`: all checks passed;
- diff whitespace checks: clean.

Truth status:

- Hermes CLI is installed and inspectable locally;
- project-owned Hermes skills are installed idempotently;
- real Hermes/Nemotron decision execution is not claimed;
- `.demo/bundles/hermes-decisions/hermes-decisions.json` is a sanitized
  deterministic fallback bundle with the NVIDIA blocker recorded.

Next issue: #9 after issue #8 handoff comment and push.

## Issue #9: Real NVIDIA OpenShell / NemoClaw Sandbox

UTC start: 2026-06-24T15:47:00Z
UTC focused validation: 2026-06-24T15:48:43Z
UTC final validation: 2026-06-24T15:51:56Z

Status: partial, external blocker for real Docker/OpenShell/NemoClaw execution.
Real OpenShell/NemoClaw execution is
externally blocked in this terminal environment because Docker/OpenShell are not
available on `PATH`.

Implemented so far:

- read issue #9 and confirmed there are no comments;
- checked current official OpenShell/NemoClaw sources and recorded current
  source refs and OpenShell installer digest;
- added project-owned OpenShell policy artifacts under `nvidia/openshell/`;
- added `agent_bounty.nvidia_runtime` with Docker/OpenShell/NemoClaw/NVIDIA
  status reporting, policy/manifest digests, credential-safe inference config
  reporting, adversarial probe plan, sanitized sandbox environment filtering,
  and `demo-nvidia-sandbox` fallback/real gate;
- updated the shared execution scrubber to treat `NVIDIA_` environment names as
  sensitive;
- added CLI commands `nvidia-runtime-status` and `demo-nvidia-sandbox`;
- documented the runtime boundary in `docs/nvidia-sandbox.md`.

Safe evidence:

```text
OpenShell main: 2c545893ed247d4e04b585377d7bda8f24fd93dd
OpenShell v0.0.38: dfd47683e7da4f1a4a8fa5d77f92d3696e6a41f9
OpenShell v0.0.68: d64542f69d06694cbd203b64929d286dd0533bbb
NemoClaw main: 17d03317b042b56da8147a2e7d1955408c11d22d
nemoclaw-community main: cea4ae01a0e2d7d359d37ed52b5bb454a226ca1b
OpenShell install.sh digest:
sha256:c15d6cb8090e1c7c8d79a320b5bcbdaf1c15c2363942d81e84b56e03b836249e

policy file digest:
sha256:0e282c88700035e86547b777415c173daa736514848705bfd36f6be2fc6636ac

manifest digest:
sha256:6235854a62d67608abe8d81018627f0a8bd2a9601c679877f88759b171d17915

effective policy digest:
sha256:9211dad2c0732aa14d07159df7ab4445f34100197c9f88cbe7879bc635b2d7a9

fallback demo bundle digest:
sha256:1b6460a7563ed6a65697a1bab85a18ddee3b4c7682eacf89554c29d39f86be78
```

Exact external blocker observed:

```text
docker executable not found on PATH; openshell executable not found on PATH.
Without Docker/OpenShell, the repo cannot create or execute a real
OpenShell/NemoClaw sandbox on this host.
```

Focused validation run:

```bash
nix develop --command python3 -m py_compile agent_bounty/nvidia_runtime.py agent_bounty/execution.py agent_bounty/cli.py tests/test_nvidia_runtime.py
nix develop --command python3 -m unittest tests.test_nvidia_runtime
nix develop --command python3 -m unittest tests.test_execution_backend
nix develop --command bash -lc 'python3 -m agent_bounty nvidia-runtime-status | python3 -m json.tool'
nix develop --command bash -lc 'python3 -m agent_bounty demo-nvidia-sandbox --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency --bundle .demo/bundles/nvidia-sandbox | python3 -m json.tool'
```

Observed results:

- NVIDIA runtime tests: 6 passed;
- execution backend tests: 6 passed, 1 skipped because OpenShell is unavailable;
- `nvidia-runtime-status`: `ok=false`, `real_backend_ready=false`;
- `demo-nvidia-sandbox`: `ok=true`, `real_backend=false`,
  `real_hermes_in_sandbox=false`, baseline/intermediate/final verification
  cases marked `not_run`.

Full validation run:

```bash
nix develop --command python3 -m compileall agent_bounty tests verifiers
nix develop --command python3 -m unittest discover -s tests
nix flake check
git diff --check --cached
git diff --check
```

Observed results:

- compileall passed;
- full test suite: 111 passed, 2 skipped;
- `nix flake check`: all checks passed;
- diff whitespace checks: clean.

Truth status:

- Docker/OpenShell/NemoClaw were not installed or visible in this terminal
  environment;
- no real sandbox, unauthorized-network denial, credential-sentinel denial, or
  three-commit verification run is claimed;
- the sanitized fallback bundle records `real_backend=false` and `not_run`
  evidence rows.

Next issue: #10 after issue #9 handoff comment and push.

## Issue #10: Real GitHub Issue / Claim / PR / Receipt Lifecycle

UTC start: 2026-06-24T15:53:00Z
UTC final validation: 2026-06-24T16:02:23Z

Status: partial, external blocker for real authenticated GitHub lifecycle.
The real authenticated GitHub lifecycle is externally blocked because this
program does not have GitHub write configuration in its environment.

Implemented so far:

- read issue #10 and confirmed there are no comments;
- audited local auth and remotes:
  `gh` is unavailable, `agent-bounty-market` pushes to
  `git@github-motoko:lk251/agent-bounty-market.git`, and the Motoko issue
  worktree has a `github` remote for `lk251/motoko`;
- inspected `lk251/motoko#1`, found no recent Motoko PRs through the connector,
  and confirmed `agent-bounty-market#7` is an unrelated demo-rehearsal PR;
- updated existing GitHub contract publication to preserve existing human issue
  text, replace old `agent-bounty-contract-v1` blocks, and reuse the previous
  contract timestamp when the same bounty/base is updated;
- added REST client and fake-client `create_pull_request` support;
- added `agent_bounty.github_live` with `demo-github-motoko-live`, safe refusal
  bundles, optional candidate branch push, real issue contract publication,
  real structured claim publication, draft PR creation, REST PR import fallback,
  protected verifier execution, and commit-status result publication;
- added GitHub live configuration placeholders to `.env.example`;
- documented the live boundary in `docs/github-live.md`.

Exact external blocker observed:

```text
gh is not installed, and github-status reports missing
AGENT_BOUNTY_GITHUB_INTEGRATION=1, AGENT_BOUNTY_GITHUB_TOKEN or GH_TOKEN,
AGENT_BOUNTY_GITHUB_REPOSITORY, and AGENT_BOUNTY_GITHUB_WEBHOOK_SECRET.
```

Safe command evidence:

```text
demo-github-motoko-live bundle digest:
sha256:0b295d84be158d79f788ac86b25491cec676cb8e6ea836f722e89886c48fc63a

demo-github-motoko-live truth labels:
ok=false
real_github=false
real_webhook=false
```

Validation run:

```bash
nix develop --command python3 -m py_compile agent_bounty/github_integration.py agent_bounty/github_live.py agent_bounty/cli.py tests/test_github_integration.py
nix develop --command python3 -m unittest tests.test_github_integration
nix develop --command python3 -m compileall agent_bounty tests verifiers
nix develop --command python3 -m unittest discover -s tests
nix flake check
git diff --check --cached
git diff --check
```

Observed results:

- GitHub integration tests: 8 passed;
- compileall passed;
- full test suite: 113 passed, 2 skipped;
- `nix flake check`: all checks passed;
- diff whitespace checks: clean.

Truth status:

- the real Motoko issue was inspected through the connector, but this repo's
  GitHub integration code did not authenticate or write real GitHub objects;
- no real issue contract update, claim comment, draft PR, commit status, or
  webhook delivery is claimed;
- `demo-github-motoko-live` produces a sanitized blocker bundle until the
  program receives reviewed GitHub credentials/configuration.

Next issue: #11 after issue #10 handoff comment and push.
