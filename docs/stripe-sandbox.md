# Stripe Sandbox Runbook

This repo's real Stripe path is sandbox-only. The Nix dev shell provides the
official `stripe==15.2.0` Python package and the Stripe CLI. Secrets stay in the
operator environment, and the repo persists only safe object IDs, digests,
statuses, and metadata needed for reconciliation.

## Setup

```bash
nix develop
cp .env.example .env
```

Set real local values in `.env` or the shell:

```bash
AGENT_BOUNTY_STRIPE_SANDBOX=1
STRIPE_TEST_SECRET_KEY=sk_test_...
STRIPE_TEST_WEBHOOK_SECRET=whsec_...
STRIPE_TEST_CONNECTED_ACCOUNT_ID=acct_...
AGENT_BOUNTY_PUBLIC_BASE_URL=http://127.0.0.1:4242
```

Never commit `.env`, API keys, webhook secrets, Checkout URLs with sensitive
client state, or full webhook payloads.

## Commands

```bash
python -m agent_bounty stripe-status

python -m agent_bounty stripe-create-checkout \
  --db .demo/stripe.sqlite3 \
  --project-id project_motoko \
  --source owner \
  --amount-cents 2500 \
  --currency usd \
  --success-url http://127.0.0.1:4242/success \
  --cancel-url http://127.0.0.1:4242/cancel

AGENT_BOUNTY_RUN_STRIPE_INTEGRATION=1 \
python -m agent_bounty stripe-automated-payment \
  --db .demo/stripe.sqlite3 \
  --project-id project_motoko \
  --source owner \
  --amount-cents 2500 \
  --currency eur \
  --payment-method pm_card_visa

python -m agent_bounty stripe-webhook-serve \
  --db .demo/stripe.sqlite3 \
  --host 127.0.0.1 \
  --port 4242

python -m agent_bounty stripe-process-events \
  --db .demo/stripe.sqlite3

stripe listen \
  --events payment_intent.succeeded,payment_intent.payment_failed,checkout.session.completed,checkout.session.expired,transfer.created,transfer.reversed \
  --forward-to localhost:4242/stripe/webhook

python -m agent_bounty stripe-attach-beneficiary \
  --db .demo/stripe.sqlite3 \
  --solver-id solver_codex_motoko_issue_1 \
  --account-id acct_...

python -m agent_bounty stripe-release-transfer \
  --db .demo/stripe.sqlite3 \
  --bounty-id bounty_motoko_issue_1

python -m agent_bounty stripe-reconcile \
  --db .demo/stripe.sqlite3 \
  --project-id project_motoko \
  --solver-id solver_codex_motoko_issue_1 \
  --bounty-id bounty_motoko_issue_1

python -m agent_bounty stripe-reconcile \
  --db .demo/stripe.sqlite3 \
  --project-id project_motoko \
  --solver-id solver_codex_motoko_issue_1 \
  --bounty-id bounty_motoko_issue_1 \
  --remote
```

## Semantics

- Checkout payment moves money into the Stripe platform sandbox.
- The automated test PaymentMethod helper is only for repeatable sandbox smoke
  tests and is gated by `AGENT_BOUNTY_RUN_STRIPE_INTEGRATION=1`.
- Use the platform/account currency for real transfer smoke tests. On the HB3
  Spanish sandbox platform, the successful end-to-end run used EUR.
- The internal project treasury is credited only from a signed, retrieved,
  validated payment completion event.
- A bounty reservation is internal ledger movement from available to reserved.
- A Connect Transfer moves platform Stripe balance to a connected account
  balance after an accepted verifier receipt.
- `demo-economic-loop` is a deterministic split-retain-spend proof by default.
  It records fake external transfer IDs and references prior real sandbox
  evidence, but it does not create a real split Connect Transfer.
- A bank payout is not part of this milestone.

Plain `stripe-reconcile` is local and safe without credentials. `--remote`
requires sandbox credentials and retrieves Stripe-side Checkout Session,
PaymentIntent, Charge, connected account, and Transfer objects, then reports
content-safe mismatches instead of performing destructive repair.

`transfer.created` is audit-only. `transfer.reversed` records manual review.
Transfer creation failures are synchronous API failures or unknown remote
outcomes recovered by idempotency key and reconciliation.
