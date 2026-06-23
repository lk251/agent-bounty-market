# Architecture

Agent Bounty Market is a local transaction core with four trust zones:

1. **Trusted orchestrator**: Python package and SQLite database in this repo.
2. **Trusted verifier**: platform-owned verifier contract under `verifiers/`.
3. **Untrusted candidate**: solver checkout, branch, and commit under test.
4. **Payment gateway**: fake deterministic gateway by default; explicit
   Stripe sandbox boundary when configured.

The orchestrator owns bounty state, idempotency, ledger entries, verification
receipts, and payout decisions. The candidate can supply code, but not the
acceptance policy.

## State

Bounties move through an explicit state machine:

```text
draft -> awaiting_funding -> funded -> open -> claimed -> submitted
-> verifying -> accepted -> payout_pending -> paid
```

The model also includes `rejected`, `expired`, `cancelled`, `refunded`, and
`payout_failed`. Invalid transitions fail closed. Rejection does not pay; an
accepted bounty still is not paid until payout release moves through
`payout_pending -> paid`.

## Money

Money is stored only as integer minor units. The append-only ledger records
stable idempotency keys, account transfers, amount, currency, related project,
bounty, solver, payout, external IDs, and timestamps. Project available and
reserved accounts are checked before outgoing transfers, and one bounty can have
only one payout row.

Project treasury, bounty, receipt, and payout currency must match. Funding,
reserve, verification, refund, and payout updates happen inside SQLite
transactions. Internal accounts are constrained non-negative, and idempotency
keys are bound to their original arguments.

## Verification

The protected v2 verifier lives under `verifiers/motoko_issue_1_v2/`. It creates
a temporary worktree for the candidate commit, uses temporary HOME/state/config
paths, scrubs the environment through the runner, exercises the real Motoko TUI
through PTYs, and emits compact JSON.

Candidate Python is never imported into the trusted verifier interpreter. The
trusted parent owns fixtures, randomized nonce values, thresholds, statistics,
digests, and verdict logic. Candidate code runs only as child processes through
the execution backend PTY/process API, and candidate stdout is treated as
observation data rather than authoritative verdict JSON.

The v2 contract checks idle short and long transcript typing, rejects transcript-
dependent ordinary input scans, and runs a real background-study typing scenario
in a separate Motoko child process while `study: evidence-store` is active.

The verification receipt binds bounty ID, project/issue, submission ID, solver
ID, candidate repo path, base SHA, candidate SHA, verifier name/version/digest,
backend name/digest, policy digest, metrics, stdout/stderr digests, result
digest, and timestamps. Payout release must reference the accepted receipt and
exact verifier, backend, and policy digests.

Verification runs are crash recoverable. A completed idempotency key replays the
same receipt. A `running` row without a receipt is treated as incomplete work
and retried instead of being returned as a completed replay. Verifier errors and
timeouts are recorded without producing payout-eligible receipts, and the bounty
leaves `verifying` so it can be retried.

## Payment Boundary

`FakePaymentGateway` is deterministic and idempotent for local tests.
The legacy stdlib Stripe smoke gateway remains isolated as deterministic support
for old tests, but the real sandbox integration uses the official
`stripe==15.2.0` Python package through `OfficialStripeClient`.

The real sandbox mapping is:

- project treasury funding request -> Stripe-hosted Checkout Session in
  payment mode;
- Checkout creation -> no internal credit;
- signed Stripe webhook -> persisted event row, then validated PaymentIntent or
  Checkout Session retrieval;
- validated `payment_intent.succeeded` or paid `checkout.session.completed` ->
  exactly one internal treasury credit;
- solver beneficiary -> retrieved test Connect account ID stored on the solver;
- accepted verifier receipt -> one Connect Transfer to the connected account;
- Transfer retrieval -> exact amount, currency, destination, transfer group,
  metadata, and `livemode=false` validation before internal settlement is marked
  paid.

Durable Stripe state is split across `funding_requests`,
`stripe_webhook_events`, and `stripe_operations`. All Stripe POST calls use a
stable idempotency key and an argument digest; reusing a key with changed
arguments fails before calling Stripe. Webhook rows retain payload digests and
safe metadata, not full unnecessary payloads or secrets.

Public Transfer events are audit/recovery events. `transfer.created` does not
settle a bounty a second time. `transfer.reversed` records a manual-review
reversal state. Stripe does not expose a public `transfer.failed` event; Transfer
creation failures are synchronous API failures or unknown remote outcomes that
must be reconciled through the operation journal and idempotency key.

Production keys, marketplace onboarding, public Connect account creation, web
UI, legal escrow handling, and bank payouts remain out of scope for this slice.
