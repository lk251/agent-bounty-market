# Stripe Sandbox Settlement Status

The old PaymentIntent smoke path has been superseded. The current milestone is
the real sandbox loop:

```text
Stripe-hosted Checkout
-> signed webhook credits internal treasury exactly once
-> accepted Motoko verifier receipt
-> one validated Connect Transfer to a test connected account
-> replay-safe reconciliation
```

Implemented in this repo:

- optional official Stripe SDK dependency pinned in `requirements-stripe.txt`;
- safe `stripe-status`;
- durable `funding_requests`, `stripe_webhook_events`, and
  `stripe_operations` tables;
- Checkout funding request creation with no treasury credit;
- official-library webhook path for real signed events;
- record-first webhook service plus `stripe-process-events` restart recovery;
- exact-once treasury credit from validated PaymentIntent/Checkout state;
- connected-account validation;
- Connect Transfer creation plus retrieval/binding validation;
- `transfer.created` audit handling and `transfer.reversed` manual-review
  handling;
- `stripe-reconcile` safe report;
- deterministic fake-client tests covering the network-free contract.

External blocker for full exit criteria in a fresh checkout:

```text
Need real Stripe sandbox credentials, webhook secret from stripe listen, and a
pre-created test connected account before producing live cs_/pi_/ch_/evt_/tr_
evidence.
```

Run local deterministic validation:

```bash
python3 -m unittest discover -s tests
python3 -m py_compile $(find agent_bounty verifiers tests -name '*.py' -print)
git diff --check
```
