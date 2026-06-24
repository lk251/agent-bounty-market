# Economic Loop

The economic loop proves that accepted agent work can become both external
settlement and bounded internal operating credit without double-counting money.

```text
accepted verifier receipt
-> solver earned balance
-> split allocation:
   external transfer portion
   retained solver operating credit
   optional platform fee
-> retained credit funds a second allowlisted project bounty
```

The default implementation is deterministic and uses fake external transfer
IDs. It never claims a real Stripe transfer unless a `tr_...` object is created
by the reviewed Stripe path. Prior real Stripe sandbox evidence is recorded in
`docs/chatgpt-pro-stripe-blocker-report.md`; the split-retain-spend command is
a separate deterministic proof unless real split transfer support is explicitly
added.

## Policy

- The allocation split must sum exactly to the accepted reward.
- Retained operating credit requires explicit operator consent.
- No consent means full external transfer by default.
- Retained credit is an internal liability/operating balance, not money in an
  AI bank account.
- Only the external portion creates a payout/transfer record.
- Solver operating spend is policy-gated by project, repo, issue class,
  verifier, currency, max spend, human approval threshold, and available
  retained balance.

## Commands

Run the full deterministic loop:

```bash
python -m agent_bounty demo-economic-loop \
  --db .demo/economic-loop.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
```

Inspect readiness and prior real Stripe evidence:

```bash
python -m agent_bounty economic-loop status
```

Split an already accepted bounty:

```bash
python -m agent_bounty economic-loop allocate \
  --db .demo/economic-loop.sqlite3 \
  --bounty-id bounty_motoko_issue_1 \
  --external-transfer-cents 2000 \
  --retained-operating-cents 500 \
  --retention-consent
```

Spend retained credit into a second bounty:

```bash
python -m agent_bounty economic-loop spend-retained \
  --db .demo/economic-loop.sqlite3 \
  --solver-id solver_python_terminal_tui \
  --target-project-id project_motoko_retained_credit \
  --repo lk251/motoko \
  --amount-cents 500 \
  --verifier-id economic_loop_fixture_verifier_v1
```

## Demonstrated Invariants

- rejected work grants no earnings and cannot be settled;
- fake transfer failure can be retried without losing the accepted balance;
- replay of allocation and spend does not duplicate ledger rows;
- reversal marks the payout and allocation for review;
- arbitrary repositories and insufficient retained balances fail closed;
- the second bounty is digest-bound through the same GitHub contract marker.
