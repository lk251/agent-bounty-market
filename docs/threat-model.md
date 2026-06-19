# Threat Model

## Protected In This Slice

- Candidate branches cannot approve themselves by editing their own tests or
  verifier files.
- Replayed funding, reserve, verification, and payout commands do not duplicate
  ledger entries or payouts.
- Insufficient project balance cannot reserve a bounty.
- Failed, malformed, timed-out, or stale verification does not pay.
- Fake gateway payout failure records `payout_failed` and can be retried safely.
- Secrets are not required for tests or demo execution.

## Not Yet Protected

This is not a production sandbox. The protected verifier imports the candidate
Motoko implementation to exercise the TUI. It runs with scrubbed environment and
temporary state, but it is not yet isolated with NemoClaw/OpenShell, network
policy, seccomp, containers, or VM boundaries.

## Next Hardening

- Run untrusted candidate work in the sponsor-prescribed isolated execution
  path.
- Add resource limits beyond wall-clock timeout and bounded captured output.
- Add Stripe webhook signature verification and idempotent event ingestion.
- Add GitHub App signature verification and repository installation scoping.
