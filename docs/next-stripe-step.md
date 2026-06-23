# Stripe Test-Mode Settlement Step

The first Stripe milestone is implemented as a test-mode boundary, not a live
marketplace integration.

Implemented:

- explicit Stripe test configuration that cannot be enabled accidentally;
- `sk_test_` and solver `acct_` validation before gateway construction;
- stdlib-only PaymentIntent funding and Transfer payout request mapping;
- Stripe external IDs stored beside the existing idempotency keys;
- PaymentIntent `latest_charge` extraction and source-backed Transfer requests
  when Stripe returns a charge ID;
- raw-payload webhook signature verification;
- idempotent `stripe_webhook_events` rows;
- manually gated `stripe-sandbox-smoke` command for real Stripe test-mode
  PaymentIntent and Transfer calls;
- duplicate webhook, payout failure, retry, and reconciliation tests.

Manual real-sandbox validation is intentionally excluded from normal CI because
it requires a local `sk_test_` key and connected test account:

```bash
AGENT_BOUNTY_STRIPE_REAL_SANDBOX=1 \
AGENT_BOUNTY_STRIPE_TEST_MODE=1 \
STRIPE_SECRET_KEY=sk_test_... \
AGENT_BOUNTY_STRIPE_SOLVER_ACCOUNTS_JSON='{"solver_stripe_smoke":"acct_..."}' \
python3 -m agent_bounty stripe-sandbox-smoke \
  --solver-id solver_stripe_smoke \
  --amount-cents 100 \
  --run-id manual-001
```

Non-goals for that milestone: web UI, GitHub webhooks, Hermes agents, real
marketplace onboarding, or production Stripe credentials.

Note: `docs/next-codex-goal-finish-real-stripe-sandbox.md` was not present in
the fetched repository when this slice was implemented. This document is the
authoritative in-repo Stripe milestone record.

Focused validation:

```bash
python3 -m unittest tests.test_payments
```

Full validation:

```bash
python3 -m unittest discover -s tests
python3 -m py_compile $(find agent_bounty verifiers tests -name '*.py' -print)
git diff --check
```
