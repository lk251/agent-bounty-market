# Judge Q&A

## 1. Is this a real marketplace?

Not yet. It is the transaction core and demo harness: funding, policy,
contract, claim, verification, settlement, replay safety, and evidence
packaging. The public marketplace UI and production operations are outside this
release candidate.

## 2. What is real in the bundle?

The bundle is `Mixed real/fallback`. It includes real local Hermes executable
evidence and prior recorded-real Stripe sandbox transfer evidence. It also
includes deterministic fallback rows for blocked live paths.

## 3. What is fake?

The winning bundle uses deterministic fake providers for the fresh split
settlement, GitHub lifecycle, project-agent decisions, solver-agent decisions,
and retained-credit follow-up bounty. Each fallback is visibly labeled.

## 4. Why use fallbacks at all?

The purpose is to prove the trusted interfaces and replay-safe economic kernel
without hiding missing credentials or runtimes. Fallbacks keep the demo
repeatable while the exact live upgrade path remains inspectable.

## 5. Does an agent control external money?

No. Retained operating credit is an internal ledger liability governed by trusted
policy. External transfers happen only through explicit payment-gateway
adapters and reconciliation.

## 6. What prevents a candidate from faking acceptance?

Payment is based on a platform-owned protected verifier bound to exact commits,
not on candidate-owned CI or a chat response. Tests include a malicious
candidate that tries to forge verifier output and is rejected.

## 7. How do you avoid double payment?

Funding, reserve, claim, verification, settlement, transfer, and retained-credit
spend paths are idempotent. Replays return the same durable rows rather than
moving value again.

## 8. How would this become a live Stripe run?

Load sandbox env, start `stripe listen`, create Checkout, process the signed
webhook, run accepted verification, attach a test connected account, release the
Connect Transfer, reconcile, then import the real fragment.

## 9. Why is this useful before production?

It narrows the hard part: whether software work can be funded, verified, and
settled by durable evidence instead of ad hoc trust. The remaining sponsor work
plugs into already-defined boundaries.

## 10. What should judges be skeptical about?

They should ask whether every claimed real component has evidence, whether
fallbacks are clearly labeled, whether blockers are visible, and whether replay
and reconciliation are deterministic. The submission checker exists to keep
those claims honest.
