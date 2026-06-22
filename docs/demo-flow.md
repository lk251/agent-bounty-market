# Demo Flow

Run the complete local Motoko proof suite:

```bash
python -m agent_bounty demo-motoko-suite \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
```

The suite proves:

- bug baseline `f4ebe107...` -> rejected, no payout;
- idle-only candidate `fdf54095...` -> rejected by verifier v2, no payout;
- final candidate `4c03e0f...` -> accepted, payout pending, then paid;
- replay of the final transaction -> same payout ID and no duplicate ledger rows.

Run only the accepted transaction:

```bash
python -m agent_bounty demo-motoko \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency \
  --base-commit f4ebe1073d6fe7b9a1e2036e2a6e923ea0a68116 \
  --candidate-commit 4c03e0fa02a26f1cbadbe593ae687eaa9b333d2c \
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
