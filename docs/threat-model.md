# Threat Model

## Protected In This Slice

- Candidate branches cannot approve themselves by editing their own tests or
  verifier files.
- Replayed funding, reserve, verification, and payout commands do not duplicate
  ledger entries or payouts.
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
- Fake gateway payout failure records `payout_failed` and can be retried safely.
- Stripe cannot be enabled accidentally: the test gateway requires explicit
  construction, an `sk_test_` key, and configured solver Connect accounts.
- Stripe webhook ingestion verifies signatures over the raw payload, rejects
  live-mode events, stores event IDs idempotently, rejects same-ID changed
  payload replays, and can settle or fail pending transfers without duplicating
  ledger rows.
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
- Add a real Stripe test-account smoke test that is manually gated by
  environment variables and never required for normal CI.
- Add GitHub App signature verification and repository installation scoping.
