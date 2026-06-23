# Agent Bounty Market

Agent Bounty Market is a small transaction core for the hackathon
loop where a funded project reserves a bounty, a solver submits a candidate
commit, a platform-owned verifier emits an immutable receipt, and the payment
gateway releases exactly one solver settlement.

This is not the marketplace UI, not legal escrow, and not a production Stripe
deployment. It is the trustable local economic kernel that later GitHub, Hermes,
and sandbox integrations can build on. The default path is dependency-light and
uses only Python's standard library. The real Stripe sandbox path is explicitly
optional and uses the official `stripe==15.2.0` Python package.

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
candidate SHA, verifier version/digest, backend/policy digests, receipt, transfer
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
recovery after incomplete `running` rows, fake-gateway payout retry, paid payout
replay, Stripe Checkout request mapping, signed webhook funding, Connect
Transfer request/retrieval binding, non-negative balances, reconciliation, and
restart idempotency.

Check the optional OpenShell backend:

```bash
python -m agent_bounty openshell-status
```

If `openshell` is not installed, this reports an exact blocker and still prints
the verifier backend and policy digests used for audit records.

## Stripe Test Sandbox

Real Stripe calls are never made by default. The real sandbox path is:

```text
Stripe-hosted Checkout payment
-> signed webhook credits internal project treasury once
-> accepted Motoko verifier receipt authorizes one Connect Transfer
-> reconciliation compares Stripe object links and internal ledger rows
```

Install the optional integration dependency outside the default test path:

```bash
python3 -m pip install -r requirements-stripe.txt
```

Check safe configuration status:

```bash
python -m agent_bounty stripe-status
```

Create a Checkout funding request:

```bash
AGENT_BOUNTY_STRIPE_SANDBOX=1 \
STRIPE_TEST_SECRET_KEY=sk_test_... \
python -m agent_bounty stripe-create-checkout \
  --db .demo/stripe.sqlite3 \
  --project-id project_motoko \
  --source owner \
  --amount-cents 2500 \
  --currency usd \
  --success-url http://127.0.0.1:4242/success \
  --cancel-url http://127.0.0.1:4242/cancel
```

Run the signed webhook endpoint locally:

```bash
AGENT_BOUNTY_STRIPE_SANDBOX=1 \
STRIPE_TEST_SECRET_KEY=sk_test_... \
STRIPE_TEST_WEBHOOK_SECRET=whsec_... \
python -m agent_bounty stripe-webhook-serve \
  --db .demo/stripe.sqlite3 \
  --host 127.0.0.1 \
  --port 4242
```

Forward Stripe CLI test events:

```bash
stripe listen \
  --events payment_intent.succeeded,payment_intent.payment_failed,checkout.session.completed,checkout.session.expired \
  --forward-to localhost:4242/stripe/webhook
```

For repeatable sandbox tests, an explicit automated PaymentMethod helper can
create and confirm a test PaymentIntent. It is separate from the hosted Checkout
path and still does not credit internal treasury until the signed event is
processed:

```bash
AGENT_BOUNTY_STRIPE_SANDBOX=1 \
AGENT_BOUNTY_RUN_STRIPE_INTEGRATION=1 \
STRIPE_TEST_SECRET_KEY=sk_test_... \
python -m agent_bounty stripe-automated-payment \
  --db .demo/stripe.sqlite3 \
  --project-id project_motoko \
  --source owner \
  --amount-cents 2500 \
  --currency usd \
  --payment-method pm_card_visa
```

Attach a pre-created test connected account and release the accepted bounty:

```bash
python -m agent_bounty stripe-attach-beneficiary \
  --db .demo/stripe.sqlite3 \
  --solver-id solver_codex_motoko_issue_1 \
  --account-id acct_...

python -m agent_bounty stripe-release-transfer \
  --db .demo/stripe.sqlite3 \
  --bounty-id bounty_motoko_issue_1
```

`stripe-reconcile` reports funding requests, webhook rows, Stripe operations,
ledger balance checks, and safe corrective actions. Add `--remote` when sandbox
credentials are configured to retrieve and compare the Checkout Session,
PaymentIntent, Charge, connected account, and Connect Transfer. Bank payout from
the connected account is outside this milestone.

If the webhook service is interrupted after recording an event but before
processing it, run:

```bash
python -m agent_bounty stripe-process-events --db .demo/stripe.sqlite3
```
