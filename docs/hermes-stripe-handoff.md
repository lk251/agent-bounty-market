# Hermes / Stripe Handoff

Future Hermes-style buyer or solver agents should call this repo's trusted CLI.
They must not hold Stripe API keys, webhook secrets, or connected-account
credentials in prompts, solver sandboxes, or candidate repositories.

Trusted operator/orchestrator responsibilities:

- keep Stripe credentials in the local environment;
- run `stripe-status`, `stripe-create-checkout`, `stripe-webhook-serve`,
  `stripe-attach-beneficiary`, `stripe-release-transfer`, and
  `stripe-reconcile`;
- inspect compact JSON outputs and safe object IDs;
- decide whether a reconciliation blocker needs manual Stripe dashboard work.

Agent responsibilities:

- choose project/bounty/solver intent;
- submit candidate commits;
- read safe receipts, ledger summaries, and reconciliation reports;
- never fabricate `cs_`, `pi_`, `ch_`, `evt_`, or `tr_` IDs.

Stripe MCP can be added later for trusted read/audit calls using OAuth or a
restricted key. MPP, Stripe Projects, Link purchases, public Connect onboarding,
and Hermes buyer/solver autonomy are outside this milestone.
