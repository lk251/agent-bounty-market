# Architecture

Agent Bounty Market is a local transaction core with four trust zones:

1. **Trusted orchestrator**: Python package and SQLite database in this repo.
2. **Trusted verifier**: platform-owned verifier contract under `verifiers/`.
3. **Untrusted candidate**: solver checkout, branch, and commit under test.
4. **Payment gateway**: fake deterministic gateway by default; explicit
   Stripe sandbox boundary when configured.
5. **GitHub coordination surface**: optional issue/comment/PR/status transport
   for bounty contracts and solver submissions.
6. **Project-agent buyer**: optional runtime boundary that proposes bounded
   bounties while trusted code enforces spending policy.
7. **Solver agents**: specialized seller profiles that underwrite, claim,
   execute, submit, and learn only through protected verification outcomes.
8. **Economic loop**: accepted solver earnings can be split into external
   settlement and retained operating credit, then used for bounded follow-up
   bounty creation.

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

Accepted work first releases the full reward from project reserved funds into
`solver:<id>:earned`. The split settlement layer can then move that exact earned
balance into:

- an external payout portion through `solver:<id>:payout_transit` to
  `solver:<id>:paid`;
- a retained operating-credit portion to
  `solver:<id>:operating_available`;
- an optional platform fee to `platform:fees`.

The split must sum exactly to the reward. Retained operating credit requires
explicit operator consent; without consent the default policy is full external
transfer. Retained credit can fund only allowlisted follow-up project bounties
through trusted host policy. It is an internal liability/operating balance, not
money in an AI-owned bank account.

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

## GitHub Boundary

The GitHub-native path is a transport around the same trusted kernel. Hidden
issue/comment/PR markers bind bounty contracts, claims, and submissions to
stable JSON digests. Webhook ingestion verifies `X-Hub-Signature-256`, stores a
unique delivery row before processing, rejects same-ID changed-payload replays,
checks repository scope, and can resume unprocessed rows after restart.

Candidate-owned GitHub checks and statuses are never authoritative. The trusted
orchestrator publishes accepted/rejected verifier results through its own
durable publication journal. Real GitHub network calls are gated by environment
credentials; local tests use `FakeGitHubClient`.

See `docs/github-native.md` for commands and the current real-integration
blocker.

## Project-Agent Boundary

The project-agent buyer is deliberately split:

- agent runtime proposes structured `project-agent-bounty-decision-v1` objects;
- trusted policy validates repo/class/verifier/currency/reward/reserve limits;
- only trusted host code can reserve funds or publish a GitHub bounty contract;
- runtime request/trace excludes Stripe and GitHub credentials;
- skill versions and digests, runtime identity, request/response digests,
  proposal digests, policy verdicts, and publication IDs are stored.

The default runtime is deterministic for tests. The gated Hermes adapter records
the exact runtime/model and refuses to run unless a reviewed Hermes project
wrapper command is configured. Issue #8 adds a live `hermes-status`,
`hermes-install-skills`, and `demo-hermes-decisions` boundary that reports
Hermes/NVIDIA/Nemotron readiness without exposing secrets. See
`docs/project-agent.md` and `docs/hermes-live-integration.md`.

## Solver-Agent Boundary

Solver agents are profile-driven sellers. A profile records specialization,
supported versions, verified history, budget, scope restrictions, attempts,
acceptance/rejection counts, cost/time summaries, and last validation. The fake
runtime evaluates all profiles against open funded contracts; trusted code
enforces claim policy before an exclusive lease is acquired.

Execution is recorded through the strongest configured backend. The current demo
uses deterministic Motoko replay and labels the backend as
`local-isolated-process-fallback`. The OpenShell/NemoClaw boundary is represented
by `nvidia-runtime-status`, `demo-nvidia-sandbox`, and the project-owned policy
under `nvidia/openshell/`; it reports a real backend only when Docker,
OpenShell, an approved sandbox, and policy digests are present. PR evidence
packages bind contract digest, solver profile, base/candidate SHAs, changed
files, command/output digests, limitations, and verification result.
Capability/economics update exactly once and only after the protected verifier
result.

Solver fit decisions can use a separate reviewed Hermes solver wrapper. The
wrapper is advisory only; trusted code still validates capability, margin,
budget, freshness, and claim exclusivity before any lease is created.

See `docs/solver-agent.md` and `docs/hermes-live-integration.md`.

## Economic-Loop Boundary

The economic-loop path composes the project-agent, solver-agent, ledger, payout,
and fake-GitHub contract boundaries. Agent output can recommend or demonstrate
the loop, but trusted code enforces allocation sums, consent, spend policy,
balance checks, replay idempotency, and digest-bound second-bounty publication.

The deterministic demo uses fake external transfer IDs and says so explicitly.
Only `tr_...` objects created and retrieved through the reviewed Stripe path are
real Stripe Connect Transfers. `demo-economic-loop-live` stages the real split
path: signed Stripe funding first, then accepted receipt, then a Connect
Transfer for only the external allocation while the retained allocation stays
inside the trusted operating-credit ledger. Prior real sandbox full-transfer
evidence is recorded separately in
`docs/chatgpt-pro-stripe-blocker-report.md`.

See `docs/economic-loop.md`.

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
- split accepted verifier receipt -> one Connect Transfer for the external
  allocation only, with retained operating credit kept internal;
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
