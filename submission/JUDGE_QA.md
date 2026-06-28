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

In the demo the project pays the accepted $25 reward. After acceptance, the
solver-side wallet/operator policy keeps $20 as operating credit and sends $5
through the Stripe settlement path to the operator account. The bounty issuer
does not control that post-acceptance split.

## 6. What prevents a candidate from faking acceptance?

Payment is based on a platform-owned protected verifier bound to exact commits,
not on candidate-owned CI or a chat response. Tests include a malicious
candidate that tries to forge verifier output and is rejected.

The recording bundle now also includes a compact Motoko verifier proof: the
original buggy version is rejected, the superficial typing fix is rejected
because background work still froze input, and the final background-study fix is
accepted with a receipt tied to the exact candidate commit.

## 7. How do you avoid double payment?

Funding, reserve, claim, verification, settlement, transfer, and retained-credit
spend paths are idempotent. Replays return the same durable rows rather than
moving value again.

Issue #21 dogfooded this loop with retained operating credit: the recorded
candidate `5ffb2835fec5d5fd9373b129f850aa52396bbd4a` produced receipt
`receipt_ecc99fd087984590ae9313933d17fa48`, verifier digest
`sha256:3429d7b5a728ba3f61db2ee0a2588d292ff5fdac361dae1570188be59e250170`,
and replay evidence for both the retained-credit spend and second settlement.

## 8. How would this become a live Stripe run?

Load sandbox env, start `stripe listen`, create Checkout, process the signed
webhook, run accepted verification, attach a test connected account, release the
Connect Transfer, reconcile, then import the real fragment.

## 9. Why is this useful before production?

It narrows the hard part: whether software work can be funded, verified, and
settled by durable evidence instead of ad hoc trust. The remaining sponsor work
plugs into already-defined boundaries.

It also turns market outcomes into data. Every claim, decline, patch, verifier
result, payout, and retained-credit spend is a labeled trajectory. Accepted paid
work is positive signal, rejected work is negative signal, and margins reveal
which agent/tool combinations actually work.

## 10. What should judges be skeptical about?

They should ask whether every claimed real component has evidence, whether
fallbacks are clearly labeled, whether blockers are visible, and whether replay
and reconciliation are deterministic. The submission checker exists to keep
those claims honest.

## Entry-Specific Competitive And Sponsor Questions

### Why is this not merely Algora or another bounty board?

Algora-style bounty boards coordinate humans around issues and payments. Agent
Bounty Market focuses on the trusted transaction kernel for agentic work:
policy-bounded funding, digest-bound contracts, exact commit verification,
idempotent settlement, retained operating credit, and release evidence. The
moat is not a listing page; it is the receipt and capability graph created by
verified work.

### What is autonomous on the buyer side?

The buyer-side agent layer can scan candidate tasks, evaluate policy and budget,
publish a bounded bounty contract, and reserve funds. In the winning bundle
those decisions are deterministic fallback decisions, not live Hermes model
reasoning, but they pass through the same policy and schema boundaries intended
for live Hermes/Nemotron-backed runs.

### What is autonomous on the seller side?

Solver profiles can discover open funded contracts, decide whether a task fits
their capability and margin, claim it, execute a deterministic replay or live
solve path, and submit evidence for protected verification. The current Motoko
fixture is deterministic; production expands this into live solver runtimes only
after sandbox and policy controls are ready.

### Why is Stripe structural rather than ordinary billing?

Stripe is structural because the product is about safe money movement after
verified work. Funding, signed webhook ingestion, internal ledger credit,
Connect transfers, split settlement, retained credit, and reconciliation are
part of the kernel. This is not just a subscription checkout wrapped around a
separate app.

### Why is Hermes structural even though the current winning bundle uses fallback decisions?

Hermes is the intended decision layer for project and solver agents. The code
already treats those decisions as schema-checked, policy-gated artifacts with
safe trace digests. The fallback decisions prove the boundary without pretending
that live Hermes/Nemotron reasoning ran in this release candidate.

### Why is NVIDIA/OpenShell structural even though the current host could not run it?

NVIDIA/OpenShell is the intended stronger execution and verification boundary:
policy manifests, sandbox digests, runtime status, and backend identity can
replace the local protected verifier without changing payment rules. The
current bundle records this path as blocked rather than hiding the missing
runtime.

### Why was the Motoko issue a legitimate first bounty?

The Motoko issue had a clear repo, exact base and candidate commits,
machine-verifiable TUI behavior, replayable tests, and observable user value.
That made it a good first bounty because acceptance could be decided by a
protected verifier rather than subjective judgment.

### What evidence demonstrates viability beyond the demo?

The repository has a SQLite transaction kernel, protected verifier, idempotent
ledger flows, fake and real-adapter boundaries, release bundle validation,
annotated tag provenance, security audit checks, mutation probes, fuzz probes,
and more than 170 tests. The demo is not only a video; it is backed by commands
that replay and audit the evidence.

### What becomes the moat or network effect?

Every accepted bounty can add solver capability evidence, project policy
history, verified receipts, and settlement/reconciliation records. Over time
the marketplace can route work based on proven ability rather than self-claims,
and successful solvers can compound retained operating credit into more work.
Those economically filtered trajectories can train future Fugu-style
orchestrators to choose the right specialist agents, skills, tools, and budgets
without claiming that this release already trained such a model.

### What must happen before production money is safe?

Fresh live Stripe split transfers, GitHub app/webhook deployment, Hermes and
OpenShell runtime hardening, operator approvals, monitoring, abuse controls,
legal review, reconciliation workflows, and incident response all need to be in
place. The current `Mixed real/fallback` release is a trusted-kernel proof, not
a production custody system.
