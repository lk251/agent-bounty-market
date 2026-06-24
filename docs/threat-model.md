# Threat Model

## Protected In This Slice

- Candidate branches cannot approve themselves by editing their own tests or
  verifier files.
- Replayed funding, reserve, verification, and settlement commands do not
  duplicate ledger entries or Connect Transfers.
- Idempotency keys are rejected if replayed with changed arguments.
- Insufficient project balance cannot reserve a bounty.
- Failed, malformed, timed-out, or stale verification does not pay.
- An accepted receipt for one candidate SHA cannot authorize payout for another
  candidate SHA, solver, issue, repo path, base SHA, or verifier digest.
- The idle-only Motoko issue #1 candidate is rejected by verifier v2 because the
  platform-owned contract measures the background-study path in a separate
  child process.
- Candidate Python is not imported into the trusted verifier interpreter. The
  verifier parent launches candidate work as child processes and computes the
  verdict from PTY/process/filesystem evidence.
- Verification receipts bind the verifier digest, execution backend digest, and
  policy digest. Payout refuses accepted receipts missing that binding.
- Incomplete `running` verification rows do not replay as successful work with a
  null receipt. They are retried; verifier errors and timeouts leave no
  payout-eligible receipt and move the bounty out of `verifying`.
- Fake gateway payout failure records `payout_failed` and can be retried safely
  in deterministic tests.
- Stripe cannot be enabled accidentally: the real sandbox path requires
  `AGENT_BOUNTY_STRIPE_SANDBOX=1`, a test-mode API key, the pinned optional
  official Stripe package, and a configured test connected account for transfer
  release.
- Stripe webhook ingestion uses raw payload signature verification through the
  official library in the real path, rejects live-mode events, stores event IDs
  idempotently, rejects same-ID changed payload replays, and can credit a
  funding request exactly once.
- Checkout creation and success redirects do not credit treasury. Only a
  signed, retrieved, validated payment completion can do that.
- Connect Transfer retrieval must match amount, currency, destination, transfer
  group, metadata, and `livemode=false`; a `tr_` prefix alone is not sufficient.
- Public `transfer.created` events are audit-only. `transfer.reversed` records
  manual-review state. There is no public `transfer.failed` handling in the real
  path.
- GitHub webhook ingestion rejects invalid `X-Hub-Signature-256` payloads before
  writing domain state, records unique deliveries before processing, rejects
  same-ID changed-payload replays, and scopes events to the configured repo.
- GitHub issue contracts, claim comments, and PR submission markers are
  digest-bound structured JSON. Ambiguous, duplicated, malformed, edited, or
  stale markers fail closed.
- Candidate-owned GitHub CI is non-authoritative. It is recorded for context but
  cannot create a verification receipt or settlement eligibility.
- Project-agent output is advisory. It cannot edit trusted policy, cannot see
  payment/GitHub credentials, cannot reserve funds, and cannot publish GitHub
  contracts directly.
- Hermes project/solver wrappers are role-specific, JSON-only, and advisory.
  They run with a scrubbed environment and must not receive Stripe keys, GitHub
  tokens, webhook secrets, SSH material, personal Motoko state, or broad project
  state.
- Project-agent malformed output, extra fields, prompt-injection attempts,
  unallowlisted repositories/classes, missing verifier IDs, overspend, and
  above-threshold spending all fail closed before money moves.
- Solver agents cannot claim unless the contract is open, repository/task class
  are allowlisted, expected cost fits operating budget, reward/currency match
  the contract, margin is non-negative, and no active lease exists.
- Solver executions record backend identity and path policy. Attempts to modify
  forbidden verifier/hidden-test paths fail before submission.
- Accepted solver outcomes update capability and settlement eligibility exactly
  once. Rejected outcomes record history but grant no earnings or verified
  capability.
- Split settlement cannot run until a protected verifier has accepted the work
  and released the reward into solver earned balance.
- Settlement allocation must sum exactly to the accepted reward. Replays with a
  different split fail closed.
- Retained solver operating credit requires explicit operator consent; the
  default without consent is full external transfer.
- Retained operating credit is policy-gated before it can fund another project:
  target project, repository, issue class, verifier, currency, amount, human
  threshold, reserve floor, and available balance are checked by trusted code.
- The deterministic economic-loop demo uses `fake_transfer_...` IDs and does
  not claim real Stripe settlement. Only reviewed Stripe-created `tr_...`
  objects are treated as real Connect Transfers.
- Transfer failure, retry, replay, and reversal paths preserve durable state
  without duplicating earned or retained balances.
- Secrets are not required for tests or demo execution.

## Not Yet Protected

This is not a production sandbox. The default backend is local process
isolation with scrubbed environment, temporary state, a new process group,
timeouts, bounded output, and resource limits where Python exposes them. It is
not equivalent to NemoClaw/OpenShell, seccomp, containers, or VM boundaries.

The OpenShell/NemoClaw path now has a project-owned deny-by-default policy and
manifest under `nvidia/openshell/`, plus `nvidia-runtime-status` and
`demo-nvidia-sandbox` commands. It only claims `real_backend=true` when a host
actually has Docker, OpenShell, an approved sandbox, and policy digests ready.

## Next Hardening

- Run untrusted candidate work in the sponsor-prescribed OpenShell/NemoClaw
  sandbox once that runtime is installed and configured for this verifier.
- Exercise the GitHub path against a real GitHub App or fine-grained token and
  webhook endpoint once credentials are available.
- Exercise the project-agent path against real Hermes/NemoClaw/Nemotron once
  the runtime is installed and the reviewed project/solver JSON wrappers are
  configured.
- Exercise the solver-agent live-solve path against real Hermes/NemoClaw/OpenShell
  and a reviewed safe live issue.
- Add a reviewed real split-Stripe-transfer adapter if the product requires
  external settlement of only part of an accepted reward. The current real
  sandbox evidence covers full-transfer settlement; split-retain-spend is
  deterministic by default.
- Replace the current local-process verifier isolation with the
  sponsor-prescribed sandbox once that runtime is available.
