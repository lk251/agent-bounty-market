# Final Voiceover

Release tag: `hackathon-mixed-rc9`.

Target length: 120 seconds. Keep the visible truth badge in frame throughout.

## Script

This is Agent Bounty Market: a transaction core for agent-native software work.
The problem is not listing tasks. The hard part is turning useful repository
work into a bounded, verifiable, replay-safe transaction.

A project starts with budget and policy. It chooses a measurable bounty, binds
the contract to a repository, verifier, reward, and acceptance rule, and records
the digest so the terms cannot silently drift.

Agents then choose whether to work. Buyer and solver decisions are stored as
bounded artifacts. In this release bundle those decisions are deterministic
fallbacks, but they pass through the same schema and policy boundary intended
for live Hermes-backed runs.

The trust boundary is the center of the product. Candidate-owned code cannot
authorize payment. A protected verifier checks the exact commit and records a
receipt. The Motoko proof shows the baseline and idle-only attempts rejected,
then the final background-study fix accepted. Settlement only follows that
receipt.

Once work is accepted, the reward is split exactly once. External transfer and
retained operating credit are separate ledger movements, with replay-safe
idempotency and reconciliation checks.

That retained credit can fund the next bounded bounty. Verified software work
becomes operating capital, and the system gains a record of what each solver and
project policy actually achieved. Issue #21 dogfooded that retained-credit loop
against this repository's release-provenance verifier.

This demo is intentionally labeled Mixed real/fallback. Real and recorded-real
evidence stay visible, and blocked sponsor paths stay blocked instead of being
claimed as live.

## One-Line Close

Verified software work became operating capital.
