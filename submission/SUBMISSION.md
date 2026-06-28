# Agent Bounty Market

One-line pitch: Agent Bounty Market turns open-source maintenance into a
verified agent labor market and a data engine for better agent orchestration.

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
7. The solver wallet keeps operating credit and can fund another bounded bounty.
8. Claims, declines, patches, verifier results, payouts, and spends become
   labeled trajectories for future orchestrators.

## Sponsor Integration Table

The complete row-by-row matrix is in `submission/SPONSOR_INTEGRATION.md`.

| Sponsor area | Implemented evidence | Current mode |
| --- | --- | --- |
| Stripe sandbox | Prior recorded-real full-transfer evidence plus reviewed split-transfer adapter | Mixed real/fallback; fresh split transfer blocked until sandbox env is loaded |
| GitHub | Contract, claim, PR marker, webhook, fake client, and publication journal | Fallback; real credentials/webhook remain gated |
| Hermes agents/skills | Hermes executable evidence, skills, wrappers, project/solver decision schemas | Mixed real/fallback; Nemotron-backed wrappers remain gated |
| NVIDIA/OpenShell/NemoClaw | Status probes, policy/manifest digests, backend boundary | Blocked; Docker/OpenShell runtime unavailable here |

## Judging Argument

Useful: converts real software maintenance into funded, verified outcomes and
high-signal training data.

Viable: projects keep budget control; solvers earn only after accepted receipts;
platform fees can be added later.

Presentation: event-backed dashboard and bundle show the operation without a
wall of JSON, including the `$25 / $20 / $5` solver wallet split.

Trustworthy: verifier ownership, exact SHA binding, idempotent ledger movement,
and honest live/replay/local mode labeling.

## Commands

```bash
nix develop --command python3 -m agent_bounty demo-build-winning-run --db .demo/winning-run.sqlite3 --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency --bundle demo/bundles/winning-run
nix develop --command python3 -m agent_bounty demo-rehearse --mode replay --bundle demo/bundles/winning-run --repeat 5
nix develop --command python3 -m agent_bounty demo-director --bundle demo/bundles/winning-run --host 127.0.0.1 --port 8788 --duration 120 --check
nix develop --command python3 -m unittest discover -s tests
nix flake check
```

## Current Limitations

See `submission/LIMITATIONS.md`. The short version: the winning bundle is a
validated `Mixed real/fallback` release candidate. It includes real Hermes
executable evidence and prior recorded-real Stripe evidence, but the complete
sponsor-integrated live path is still blocked by external runtime and credential
setup.
