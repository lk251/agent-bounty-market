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
