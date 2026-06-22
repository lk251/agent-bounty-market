# Next Stripe Step

Do not add real Stripe calls until the local core remains green under the v2
verifier and exactly-once fake gateway suite.

The next Stripe milestone should be test-mode only:

1. Add explicit Stripe test configuration that cannot be enabled accidentally.
2. Map fake gateway operations to Stripe test-mode PaymentIntent/Transfer
   equivalents, preserving integer minor units and currency checks.
3. Store Stripe external IDs beside existing idempotency keys.
4. Add webhook ingestion with signature verification and idempotent event rows.
5. Prove duplicate webhooks, payout failure, retry, and reconciliation against a
   test database before any production key or live account is considered.

Non-goals for that milestone: web UI, GitHub webhooks, Hermes agents, real
marketplace onboarding, or production Stripe credentials.
