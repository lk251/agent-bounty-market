# Demo Presentation

The presentation layer is dependency-free. It reads persisted SQLite records,
captures a sanitized evidence bundle, and writes a static dashboard HTML file.
It is designed for three truthful modes:

- `live`: refuses unless real GitHub, Hermes/NVIDIA/OpenShell, and Stripe
  sandbox prerequisites are configured;
- `replay`: validates a previously captured sanitized bundle and renders it;
- `local`: deterministic fake-provider development run with an unmistakable
  `Local simulation` badge.

## Commands

```bash
python -m agent_bounty demo-preflight --mode local
python -m agent_bounty demo-preflight --mode live

python -m agent_bounty demo-local \
  --db .demo/local.sqlite3 \
  --bundle .demo/bundles/local-run \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency

python -m agent_bounty demo-rehearse --mode local \
  --db .demo/rehearsal-local.sqlite3 \
  --bundle .demo/bundles/local-rehearsal \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency

python -m agent_bounty demo-replay --bundle .demo/bundles/local-rehearsal
python -m agent_bounty demo-rehearse --mode replay --bundle .demo/bundles/local-rehearsal
python -m agent_bounty demo-live
python -m agent_bounty demo-reset --yes
```

`demo-reset` only deletes paths under `.demo`; it refuses any other target.

## Bundle Files

Each bundle directory contains:

- `manifest.json`: schema, mode, fake/real marker, bundle digest, file digests;
- `bundle.json`: sanitized run data, persisted table snapshot, timeline, and
  summary;
- `dashboard.html`: static event-backed presentation surface.

Validation checks schema, file digests, mode consistency, fake-provider truth,
and the visible mode badge. A fake bundle cannot be relabeled as live.

## Current Truth Boundary

The implemented local rehearsal proves the core operation with fake providers.
The prior real Stripe full-transfer run remains recorded in
`docs/chatgpt-pro-stripe-blocker-report.md`, but there is not yet an
authenticated recorded-real bundle for the full GitHub + Hermes/NVIDIA + Stripe
split-retain-spend presentation.
