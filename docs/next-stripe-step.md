# Stripe Test-Mode Settlement Step

The first Stripe milestone is implemented as a test-mode boundary, not a live
marketplace integration.

Implemented:

- explicit Stripe test configuration that cannot be enabled accidentally;
- `sk_test_` and solver `acct_` validation before gateway construction;
- stdlib-only PaymentIntent funding and Transfer payout request mapping;
- Stripe external IDs stored beside the existing idempotency keys;
- raw-payload webhook signature verification;
- idempotent `stripe_webhook_events` rows;
- duplicate webhook, payout failure, retry, and reconciliation tests.

Non-goals for that milestone: web UI, GitHub webhooks, Hermes agents, real
marketplace onboarding, or production Stripe credentials.

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
