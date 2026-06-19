# Demo Flow

Run the complete local Motoko transaction:

```bash
python -m agent_bounty demo-motoko \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency \
  --base-commit f4ebe1073d6fe7b9a1e2036e2a6e923ea0a68116 \
  --candidate-commit fdf54095b5cb8aca81984993bcd38176ccadad32 \
  --funding-cents 2500 \
  --reward-cents 2500
```

For idempotency replay, use a persistent database and run the same command
twice:

```bash
python -m agent_bounty demo-motoko --db /tmp/agent-bounty-demo.sqlite3 ...
python -m agent_bounty demo-motoko --db /tmp/agent-bounty-demo.sqlite3 ...
```

For a no-payout failure path, pass a stale or mismatched candidate commit:

```bash
python -m agent_bounty demo-motoko \
  --db /tmp/agent-bounty-fail.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency \
  --base-commit f4ebe1073d6fe7b9a1e2036e2a6e923ea0a68116 \
  --candidate-commit 69dad1c \
  --funding-cents 2500 \
  --reward-cents 2500
```
