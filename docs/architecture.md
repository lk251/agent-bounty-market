# Architecture

Agent Bounty Market is a local transaction core with four trust zones:

1. **Trusted orchestrator**: Python package and SQLite database in this repo.
2. **Trusted verifier**: platform-owned verifier contract under `verifiers/`.
3. **Untrusted candidate**: solver checkout, branch, and commit under test.
4. **Payment gateway**: fake deterministic gateway now, Stripe boundary later.

The orchestrator owns bounty state, idempotency, ledger entries, verification
receipts, and payout decisions. The candidate can supply code, but not the
acceptance policy.

## State

Bounties move through an explicit state machine:

```text
draft -> awaiting_funding -> funded -> open -> claimed -> submitted
-> verifying -> accepted | rejected -> payout_pending -> paid
```

The model also includes `expired`, `cancelled`, `refunded`, and
`payout_failed`. Invalid transitions fail closed.

## Money

Money is stored only as integer minor units. The append-only ledger records
stable idempotency keys, account transfers, amount, currency, related project,
bounty, solver, payout, external IDs, and timestamps. Project available and
reserved accounts are checked before outgoing transfers, and one bounty can have
only one payout row.

## Verification

The protected verifier creates a temporary worktree for the candidate commit,
uses temporary HOME/state/config paths, scrubs the environment, exercises the
real Motoko TUI through a PTY, and emits compact JSON. The verifier receipt binds
the bounty, base commit, candidate commit, verifier digest, metrics, output
digests, and timestamps.

## Payment Boundary

`FakePaymentGateway` is deterministic and idempotent for local tests. The
`StripePaymentGateway` class is a deliberate skeleton that refuses accidental
use until explicit test-mode configuration and webhook handling are added.
