# Typeform Final Answers

Status: draft until `[FINAL_TWEET_URL]`, `[REPO_URL]`, and team fields are
filled by the operator.

## Project Name

Agent Bounty Market

## One-line Description

A dependency-light transaction kernel where projects fund bounded software
tasks, agents claim work, a protected verifier accepts exact commits, and
settlement happens once.

## Problem

Software projects have a long tail of valuable maintenance and polish work that
is hard to coordinate with ad hoc trust. Paying agents or humans safely requires
clear task boundaries, verifiable acceptance, replay-safe settlement, and honest
evidence about what actually ran.

## Solution / How It Works

Agent Bounty Market models the lifecycle:

```text
fund -> reserve -> claim -> submit exact commit -> protected verification -> accepted receipt -> settlement -> retained operating credit -> follow-up bounty
```

The trusted kernel stores ledger movements, idempotency keys, policy decisions,
verification receipts, evidence fragments, and release-bundle provenance. The
winning package is labeled `Mixed real/fallback` so judges can distinguish real,
recorded-real, fallback, and blocked paths.

The final recording package shows a concrete Motoko issue: baseline rejected,
idle-only candidate rejected, final background-study fix accepted. It also
shows issue #21 dogfooding retained operating credit into this repository's
release-provenance verifier, with replay evidence for the spend and settlement.

## Why Useful

It demonstrates a practical route from "this repo needs work" to "this exact
commit was accepted and paid once" without letting candidate-owned code, model
output, or social claims authorize payment.

## Business Model / Viability

Projects fund bounties. Solvers earn after accepted receipts. The platform can
charge a success fee and optionally let trusted retained operating credit fund
more work, bounded by policy. The moat is a growing graph of verified work,
solver capability records, project policies, and replayable receipts.

## Nous / Hermes Use

Hermes is structural as the intended project/solver agent layer: project agents
decide what bounties to fund, solver agents decide what work to claim, and
skills/wrappers create inspectable JSON decisions. The current winning bundle
uses deterministic fallback decisions, while recording real local Hermes
executable evidence and exact blockers for live Hermes/Nemotron-backed runs.

## NVIDIA Use

NVIDIA/OpenShell/NemoClaw is structural as the intended stronger execution
boundary for live verification and agent work. The current host did not have the
runtime available, so the release keeps a fallback verifier and records policy,
manifest digests, and blockers rather than claiming a live NVIDIA run.

## Stripe Use

Stripe is structural because money movement is part of the product, not just
ordinary billing. The repository includes sandbox funding/webhook/Connect
settlement code, a prior recorded-real full-transfer fragment, split-settlement
adapter and reconciliation paths, and a deterministic fallback in the winning
bundle until fresh sandbox credentials are loaded.

## Technical Architecture

- Python standard library plus SQLite transaction kernel.
- Deterministic fake providers for reproducible demos.
- Protected verifier boundary for exact commit acceptance.
- GitHub marker/webhook schemas for contracts, claims, submissions, and result
  publication.
- Stripe adapter, signed webhook handling, idempotent settlement, and
  reconciliation.
- Evidence fragments with truth status and downgrade protection.
- Release bundle with manifest, attestation, truth matrix, and annotated tag
  provenance.
- Security audit harness with model checks, mutation probes, fuzz probes,
  path-boundary checks, and content-safe secret scan.

## Repository URL

```text
[REPO_URL]
```

## Demo / Tweet URL

```text
[FINAL_TWEET_URL]
```

## Team / Member Fields

```text
[TEAM_NAME]
[TEAM_MEMBER_NAMES]
[CONTACT_EMAIL_OR_HANDLE]
```

## Limitations

The release is `Mixed real/fallback`, not all-live. Fresh split Stripe
transfer, real GitHub transport, Hermes/Nemotron decisions, and
NVIDIA/OpenShell execution require configured credentials or runtimes. The
current package is a trusted kernel and demo harness, not a production
marketplace or regulated custody product.
