# Real GitHub Lifecycle

Issue #10 adds the live GitHub issue -> claim -> PR -> protected-verification
receipt boundary. The deterministic fake-GitHub demo still exists, but the live
command refuses unless authenticated GitHub write configuration is present.

## Commands

Safe status:

```bash
python -m agent_bounty github-status
```

Live run or truthful blocker:

```bash
python -m agent_bounty demo-github-motoko-live \
  --db .demo/github-live.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
```

When explicitly approved, the command can push the exact final candidate SHA to
the Motoko GitHub remote before opening a draft PR:

```bash
python -m agent_bounty demo-github-motoko-live \
  --db .demo/github-live.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency \
  --push-branch
```

## Required Configuration

Set these only in an untracked `.env`, shell environment, or secret store:

```text
AGENT_BOUNTY_GITHUB_INTEGRATION=1
AGENT_BOUNTY_GITHUB_TOKEN=...
AGENT_BOUNTY_GITHUB_REPOSITORY=lk251/motoko
AGENT_BOUNTY_GITHUB_WEBHOOK_SECRET=...
```

`GH_TOKEN` may be used instead of `AGENT_BOUNTY_GITHUB_TOKEN`.

## Current HB3 Blocker

At implementation time:

- `gh` was not installed;
- `github-status` reported no `AGENT_BOUNTY_GITHUB_INTEGRATION=1`;
- no `AGENT_BOUNTY_GITHUB_TOKEN` or `GH_TOKEN` was present for the program;
- no `AGENT_BOUNTY_GITHUB_REPOSITORY` was configured;
- no `AGENT_BOUNTY_GITHUB_WEBHOOK_SECRET` was configured.

The GitHub connector can read and comment on issues for Codex, but that is not
the same as an authenticated run by this repository's GitHub integration code.
The live demo therefore writes a sanitized bundle with `real_github=false`.

## Safety Rules

- Existing Motoko issue text is preserved. The machine contract updater removes
  old `agent-bounty-contract-v1` blocks and appends exactly one canonical block.
- Contract timestamps are reused across updates when the existing contract
  matches the same bounty/base, keeping the contract digest stable.
- The draft PR path is explicit and never merges.
- Candidate CI is advisory only; `agent-bounty/protected-verifier` remains the
  authoritative result.
- If no inbound webhook is captured, the run must say `real_webhook=false` and
  treat REST polling/import as a fallback, not as webhook evidence.
