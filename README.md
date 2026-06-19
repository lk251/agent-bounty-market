# Agent Bounty Market

Agent Bounty Market is a small, stdlib-only transaction core for the hackathon
loop where a funded project reserves a bounty, a solver submits a candidate
commit, a platform-owned verifier emits an immutable receipt, and the payment
gateway releases exactly one payout.

This is not the marketplace UI, not a production Stripe integration, and not a
secure sandbox. It is the trustable local economic kernel that the later GitHub,
Stripe, Hermes, and NVIDIA safety integrations can build on.

## Demo

```bash
python -m agent_bounty demo-motoko \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency \
  --base-commit f4ebe1073d6fe7b9a1e2036e2a6e923ea0a68116 \
  --candidate-commit fdf54095b5cb8aca81984993bcd38176ccadad32 \
  --funding-cents 2500 \
  --reward-cents 2500
```

The command creates a temporary SQLite database by default and prints compact
JSON containing project balances, bounty state, verification receipt, solver
earnings, payout ID, and reconciliation status.

## Tests

```bash
python3 -m unittest discover -s tests
```

The tests cover state-machine failures, insufficient funds, claim exclusivity,
idempotent funding/reserve/verification/payout replay, failed verification with
no payout, malformed verifier output, timeout handling, payout retry, ledger
reconciliation, and a real Motoko fixture integration when the fixture checkout
is present.
