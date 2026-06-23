# ChatGPT Pro Handoff: Stripe Sandbox Blocker

Date: 2026-06-23
Repo: `/home/mares/repos/agent-bounty-market`
Branch pushed: `origin/main`

## Current State

The implementation work for the real Stripe sandbox settlement loop is as far
as Codex can take it without external Stripe sandbox setup.

Relevant pushed commits before this Nix-shell update:

```text
d51a62b Add Stripe blocker handoff for ChatGPT Pro
1303ad1 Require remote reconciliation for Stripe demo
74c93d3 Add remote Stripe reconciliation checks
3b60d3b Add gated automated Stripe payment helper
b764bab Harden Stripe webhook recovery path
```

The Motoko hackathon branch was also checked. `github/master` has no commits
missing from `github/bounty/issue-1-tui-input-latency`; the comparison only
shows hackathon-branch-only commits.

## What Is Implemented

- Nix dev shell support for Python 3.12, the pinned official Stripe SDK
  `stripe==15.2.0`, Git, and the Stripe CLI.
- Optional official Stripe SDK dependency remains pinned in
  `requirements-stripe.txt` as `stripe==15.2.0` for non-Nix fallback use.
- `stripe-status` with safe blocker output and live-key/live-object guards.
- Durable SQLite tables for funding requests, Stripe operations, and webhook
  event recovery.
- Stripe-hosted Checkout creation that does not credit internal treasury.
- Separate integration-gated automated test PaymentMethod helper.
- Official-library webhook ingestion using raw-body signature verification.
- Record-first webhook server and `stripe-process-events` restart recovery.
- Exact-once treasury credit from validated signed payment completion.
- Connected-account validation.
- Connect Transfer creation, immediate retrieval, and binding validation.
- `transfer.created` as audit-only and `transfer.reversed` as manual review.
- `stripe-reconcile --remote`, which retrieves and compares Checkout Session,
  PaymentIntent, Charge, connected account, and Connect Transfer.
- `demo-stripe-motoko` now requires remote reconciliation before reporting
  success.

## Why Codex Is Blocked

The remaining exit criteria require real Stripe sandbox artifacts:

```text
cs_... Checkout Session
pi_... PaymentIntent
ch_... Charge
evt_... signed webhook event
tr_... Connect Transfer
```

Those cannot be produced without Stripe sandbox credentials, a webhook secret
from `stripe listen`, and a pre-created test connected account. The Nix dev
shell now provides the pinned Stripe SDK and Stripe CLI.

Current safe `stripe-status` output:

```json
{"blockers":["set AGENT_BOUNTY_STRIPE_SANDBOX=1","set STRIPE_TEST_SECRET_KEY","set STRIPE_TEST_WEBHOOK_SECRET from stripe listen","set STRIPE_TEST_CONNECTED_ACCOUNT_ID to a test connected account"],"connected_account":null,"ok":false,"platform_account":null,"sandbox_enabled":false,"schema":"agent-bounty-stripe-status-v1","stripe_cli":"stripe version 1.41.2","stripe_package_required":"stripe==15.2.0","stripe_package_version":"15.2.0","webhook_secret_configured":false}
```

## Validation Already Passed

Run under `nix develop` on HB3:

```bash
nix develop --command python3 -m compileall agent_bounty tests verifiers
nix develop --command python3 -m unittest tests.test_payments
nix develop --command python3 -m unittest discover -s tests
nix flake check
git diff --check
```

Results:

```text
tests.test_payments: 29 tests OK, 1 skipped
full test suite: 59 tests OK, 2 skipped
nix flake check: all checks passed
git diff --check: clean
origin/main matched local HEAD before this update:
d51a62b073a7fe87ad948759732899507cc60967
```

Note: this host does not expose plain `python3` outside the Nix dev shell, so
the authoritative local commands use `nix develop --command python3 ...`.

## What ChatGPT Pro Should Do Next

Do not commit secrets. Use placeholders in docs and only pass real values
through the local environment.

Suggested setup:

```bash
cd /home/mares/repos/agent-bounty-market
nix develop

export AGENT_BOUNTY_STRIPE_SANDBOX=1
export AGENT_BOUNTY_RUN_STRIPE_INTEGRATION=1
export STRIPE_TEST_SECRET_KEY=sk_test_...
export STRIPE_TEST_WEBHOOK_SECRET=whsec_...
export STRIPE_TEST_CONNECTED_ACCOUNT_ID=acct_...
export AGENT_BOUNTY_PUBLIC_BASE_URL=http://127.0.0.1:4242

python3 -m agent_bounty stripe-status
```

Then run the real sandbox loop:

```bash
python3 -m agent_bounty stripe-webhook-serve \
  --db .demo/stripe.sqlite3 \
  --host 127.0.0.1 \
  --port 4242
```

In another shell, after `stripe listen` forwards to
`localhost:4242/stripe/webhook`:

```bash
python3 -m agent_bounty demo-stripe-motoko \
  --db .demo/stripe.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
```

If using the automated helper instead of hosted Checkout:

```bash
python3 -m agent_bounty stripe-automated-payment \
  --db .demo/stripe.sqlite3 \
  --project-id project_motoko \
  --source owner \
  --amount-cents 2500 \
  --currency usd \
  --payment-method pm_card_visa
```

Finally verify:

```bash
python3 -m agent_bounty stripe-reconcile \
  --db .demo/stripe.sqlite3 \
  --project-id project_motoko \
  --solver-id solver_codex_motoko_issue_1 \
  --bounty-id bounty_motoko_issue_1 \
  --remote
```

## Evidence Needed To Unblock Completion

Please preserve only safe compact output, not secrets:

- Checkout Session ID (`cs_...`) or automated PaymentIntent ID (`pi_...`);
- PaymentIntent ID (`pi_...`);
- Charge ID (`ch_...`);
- signed webhook event ID (`evt_...`);
- Connect Transfer ID (`tr_...`);
- connected account ID (`acct_...`);
- replay flags showing no duplicate credit, receipt, transfer, or ledger entry;
- `stripe-reconcile --remote` JSON showing:
  - `ledger_reconciled: true`;
  - `remote_checked: true`;
  - `remote_reconciled: true`;
  - empty remote mismatches.

Once those are available, the original Stripe goal can be marked complete.
