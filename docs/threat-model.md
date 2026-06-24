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
- Secrets are not required for tests or demo execution.

## Not Yet Protected

This is not a production sandbox. The default backend is local process
isolation with scrubbed environment, temporary state, a new process group,
timeouts, bounded output, and resource limits where Python exposes them. It is
not equivalent to NemoClaw/OpenShell, seccomp, containers, or VM boundaries.

The OpenShell backend is adapter-ready and reports a policy digest, but it only
runs when a host has an approved `openshell` sandbox available.

## Next Hardening

- Run untrusted candidate work in the sponsor-prescribed OpenShell/NemoClaw
  sandbox once that runtime is installed and configured for this verifier.
- Add GitHub App signature verification and repository installation scoping.
- Replace the current local-process verifier isolation with the
  sponsor-prescribed sandbox once that runtime is available.
