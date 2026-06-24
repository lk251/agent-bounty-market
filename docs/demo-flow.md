# Demo Flow

Run the complete local Motoko proof suite:

```bash
python -m agent_bounty demo-motoko-suite \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
```

The suite proves:

- synthetic malicious candidate -> rejected, no trusted-policy mutation;
- bug baseline `f4ebe107...` -> rejected, no payout;
- idle-only candidate `fdf54095...` -> rejected by verifier v2, no payout;
- final candidate `4c03e0f...` -> accepted, settlement pending, then paid;
- replay of the final transaction -> same receipt and payout ID, with no
  duplicate ledger rows.

The compact JSON distinguishes candidate-owned code (`candidate_sha`), trusted
policy (`verifier_version`, `verifier_digest`), isolated execution (`backend`,
`backend_digest`, `policy_digest`), measured evidence (`metrics`), and transfer
eligibility (`receipt.accepted`, `bounty.accepted_receipt_id`, `payout`).

If a verifier process crashes after a run row is created but before a receipt is
written, rerunning the same idempotency key resumes that incomplete run instead
of reporting a replay with a null receipt.

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

## Stripe Sandbox Demo

The real Stripe sandbox demo is deliberately split across trusted commands:

1. `stripe-status` checks safe configuration and exact blockers.
2. `stripe-create-checkout` creates a server-owned funding request and hosted
   Checkout Session. This credits zero internal treasury.
   `stripe-automated-payment` is the separate integration-gated test
   PaymentMethod helper for repeatable smoke runs.
3. `stripe-webhook-serve` verifies raw signed events, durably records them,
   returns 2xx, and then processes them. `stripe-process-events` recovers rows
   left recorded after restart.
4. The normal Motoko verifier flow accepts the exact candidate commit.
5. `stripe-attach-beneficiary` validates a pre-created test connected account.
6. `stripe-release-transfer` creates and retrieves one Connect Transfer.
7. `stripe-reconcile` compares the internal ledger and Stripe operation rows.
   With `--remote`, it also retrieves the Checkout Session, PaymentIntent,
   Charge, connected account, and Transfer for safe mismatch reporting.

For the split settlement loop, use `demo-economic-loop-live` instead of
`stripe-release-transfer`. It stages the same signed funding requirement, then
settles a 2500-cent accepted reward as 2000 cents external Stripe transfer plus
500 cents retained operating credit, and spends the retained credit into a
second bounded bounty. The retained credit is internal ledger state and is not
included in the Stripe transfer amount.

Use `nix develop` for the pinned official Stripe SDK and Stripe CLI. The default
demo and CI remain secret-free and use deterministic fake clients.
