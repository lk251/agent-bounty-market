# GitHub Native Bounty Spine

The GitHub integration is an optional boundary around the local economic
kernel. It lets GitHub issues, comments, pull requests, and platform-owned
publication records drive the same durable bounty state that the local demos
already use.

It is disabled unless explicitly configured. Tests and the local Motoko demo use
`FakeGitHubClient`; real network calls require environment credentials and pass
through `GitHubRestClient`.

## Authority Model

GitHub is used as the public coordination surface, not as the authority for
money or acceptance.

- A hidden `agent-bounty-contract-v1` JSON block binds project, repo, issue,
  base commit, reward, funding/reserve IDs, verifier identity, path policy,
  lease policy, and a digest.
- Claim comments use `agent-bounty-claim-v1` and can only move an open bounty to
  claimed when their digest, solver, bounty, and contract match.
- Pull request bodies use `agent-bounty-submission-v1`; the active claimant,
  base SHA, candidate SHA, issue number, repo, and contract digest must match.
- Candidate-owned checks, statuses, and workflow events are recorded only as
  non-authoritative events. They never create an accepted receipt.
- Verification results are published by the trusted orchestrator as a commit
  status when possible, with durable publication idempotency and a structured
  comment fallback reserved for later surfaces.

## Webhook Ingestion

Signed webhook ingestion is record-first and replay-safe:

- `X-Hub-Signature-256` must validate against
  `AGENT_BOUNTY_GITHUB_WEBHOOK_SECRET`.
- `X-GitHub-Delivery` is unique. Same delivery and same payload is a replay;
  same delivery with changed payload is rejected.
- Repository and optional installation identity are checked before domain state
  changes.
- Invalid signatures create no domain state.
- Events are stored with safe metadata and digests, then processed by
  `github-process-events`, so restart recovery can continue from recorded rows.

## Commands

Configuration status:

```bash
python -m agent_bounty github-status
```

Publish/import/show the issue contract:

```bash
python -m agent_bounty github-publish-bounty --db market.sqlite3 --bounty-id bounty_id --repo owner/repo
python -m agent_bounty github-import-bounty --db market.sqlite3 --repo owner/repo --issue-number 1
python -m agent_bounty github-show-contract --db market.sqlite3 --repo owner/repo --issue-number 1
```

Run webhook ingestion and recovery:

```bash
python -m agent_bounty github-webhook-serve --db market.sqlite3 --host 127.0.0.1 --port 4243
python -m agent_bounty github-process-events --db market.sqlite3
```

Run the local fake-GitHub Motoko lifecycle with the real protected verifier:

```bash
python -m agent_bounty demo-github-motoko \
  --db .demo/github.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
```

Real GitHub lifecycle command:

```bash
python -m agent_bounty demo-github-motoko-live \
  --db .demo/github-live.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
```

See `docs/github-live.md` for the live configuration gates and current blocker
semantics.

## Current External Blocker

The fake/client/event-contract implementation and Motoko verifier demo are
complete. Real GitHub end-to-end execution remains gated on:

- `AGENT_BOUNTY_GITHUB_INTEGRATION=1`
- `AGENT_BOUNTY_GITHUB_TOKEN` or `GH_TOKEN`
- `AGENT_BOUNTY_GITHUB_REPOSITORY=owner/repo`
- `AGENT_BOUNTY_GITHUB_WEBHOOK_SECRET`

`github-status` reports these blockers without printing secrets.
