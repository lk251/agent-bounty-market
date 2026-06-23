# Agent Bounty Market

Agent Bounty Market is a small, stdlib-only transaction core for the hackathon
loop where a funded project reserves a bounty, a solver submits a candidate
commit, a platform-owned verifier emits an immutable receipt, and the payment
gateway releases exactly one payout.

This is not the marketplace UI, not a production Stripe integration, and not a
secure sandbox. It is the trustable local economic kernel that the later GitHub,
Hermes, and NVIDIA safety integrations can build on. Stripe support is currently
limited to an explicitly configured test-mode boundary and signed webhook
ingestion.

Product thesis: agent work needs an economic kernel that can prove exactly what
was funded, claimed, verified, accepted, and paid before it touches real money.
This repo keeps that kernel small enough to audit.

## Demo

Run the complete Motoko issue #1 proof suite:

```bash
python -m agent_bounty demo-motoko-suite \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
```

The suite rejects a synthetic malicious candidate, rejects the bug baseline,
rejects the idle-only candidate, accepts the final background-study fix, pays
once, replays the final transaction, and prints compact JSON with project funds,
candidate SHA, verifier version/digest, backend/policy digests, receipt, payout
ID, and reconciliation status.

Run one accepted transaction:

```bash
python -m agent_bounty demo-motoko \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency \
  --base-commit f4ebe1073d6fe7b9a1e2036e2a6e923ea0a68116 \
  --candidate-commit 4c03e0fa02a26f1cbadbe593ae687eaa9b333d2c \
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

The tests cover valid settlement, invalid transitions, insufficient funds,
duplicate funding/reserve, exclusive claims, wrong-solver submission, stale SHA
rejection, baseline/intermediate/final Motoko verdicts, candidate-owned verifier
irrelevance, timeout/malformed verifier output, receipt binding, verifier
recovery after incomplete `running` rows, payout retry, paid payout replay,
Stripe test-mode request mapping, signed webhook replay, non-negative balances,
reconciliation, and restart idempotency.

Check the optional OpenShell backend:

```bash
python -m agent_bounty openshell-status
```

If `openshell` is not installed, this reports an exact blocker and still prints
the verifier backend and policy digests used for audit records.
