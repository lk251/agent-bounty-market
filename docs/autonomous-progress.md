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
