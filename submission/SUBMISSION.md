# Agent Bounty Market

One-line pitch: Agent Bounty Market turns neglected software tasks into funded,
verified, replay-safe work performed by specialized agents.

## Problem

Useful software maintenance often stalls because tasks are vague, trust is hard,
and payment depends on human review or manual coordination. Agent work makes
this worse unless the system can prove exactly what was funded, claimed,
verified, accepted, and settled.

## How It Works

1. A project defines budget and policy.
2. A project agent proposes measurable bounties and trusted code enforces the
   policy.
3. A machine-readable GitHub contract binds the bounty to repo, issue, verifier,
   reward, and commit constraints.
4. Specialized solver agents decline or claim based on capability, economics,
   and scope.
5. The trusted verifier runs against exact commits and emits a receipt.
6. Settlement moves money exactly once, with replay-safe ledger entries.
7. Retained operating credit can fund another bounded bounty.

## Sponsor Integration Table

| Sponsor area | Current status |
| --- | --- |
| Stripe sandbox | Prior real full-transfer sandbox evidence is documented; reviewed split-transfer adapter exists; fresh split run is blocked until Stripe sandbox env is loaded. |
| GitHub | Fake client and durable contract/webhook/publication spine implemented; real credentials/webhook remain gated. |
| Hermes agents/skills | Hermes executable is installed and verified; project/solver skill/profile/runtime interfaces exist; real Nemotron-backed wrapper remains gated. |
| NVIDIA/OpenShell/NemoClaw | Adapter/status boundary implemented; Docker/OpenShell runtime is not available in this environment. |

## Judging Argument

Useful: converts real software maintenance into funded, verified outcomes.

Viable: projects keep budget control; solvers earn only after accepted receipts;
platform fees can be added later.

Presentation: event-backed dashboard and bundle show the operation without a
wall of JSON.

Trustworthy: verifier ownership, exact SHA binding, idempotent ledger movement,
and honest live/replay/local mode labeling.

## Commands

```bash
nix develop --command python3 -m agent_bounty demo-build-winning-run --db .demo/winning-run.sqlite3 --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency --bundle demo/bundles/winning-run
nix develop --command python3 -m agent_bounty demo-rehearse --mode replay --bundle demo/bundles/winning-run --repeat 5
nix develop --command python3 -m unittest discover -s tests
nix flake check
```

## Current Limitations

See `submission/LIMITATIONS.md`. The short version: the winning bundle is a
validated `Mixed real/fallback` release candidate. It includes real Hermes
executable evidence and prior recorded-real Stripe evidence, but the full live
sponsor-integrated path is still blocked by external runtime and credential
setup.
