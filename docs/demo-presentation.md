# Demo Presentation

The presentation layer is dependency-free. It reads persisted SQLite records,
captures a sanitized evidence bundle, and writes a static dashboard HTML file.
It is designed for three truthful modes:

- `live`: refuses unless real GitHub, Hermes/NVIDIA/OpenShell, and Stripe
  sandbox prerequisites are configured;
- `replay`: validates a previously captured sanitized bundle and renders it;
- `local`: deterministic fake-provider development run with an unmistakable
  `Local simulation` badge.

The hackathon release candidate uses a checked-in mixed bundle at
`demo/bundles/winning-run`. It includes a truth matrix with `real`,
`recorded-real`, `fallback`, and `blocked` rows and displays a
`Mixed real/fallback` badge.

For recording, the preferred surface is the bundle-backed director mode. It
generates a seven-scene, two-minute static presentation from the same validated
bundle data and keeps presenter notes out of the record route.

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

python -m agent_bounty demo-build-winning-run \
  --db .demo/winning-run.sqlite3 \
  --bundle demo/bundles/winning-run \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency

python -m agent_bounty demo-rehearse \
  --mode replay \
  --bundle demo/bundles/winning-run \
  --repeat 5

python -m agent_bounty demo-serve \
  --bundle demo/bundles/winning-run \
  --host 127.0.0.1 \
  --port 8787

python -m agent_bounty demo-serve \
  --bundle demo/bundles/winning-run \
  --check

python -m agent_bounty demo-director \
  --bundle demo/bundles/winning-run \
  --host 127.0.0.1 \
  --port 8788 \
  --duration 120 \
  --check

python -m agent_bounty demo-director \
  --bundle demo/bundles/winning-run \
  --host 127.0.0.1 \
  --port 8788 \
  --duration 120

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
- `recording-timeline.md`: deterministic two-minute recording cues.
- `director.html`: interactive presenter view with notes.
- `director-record.html`: clean capture route with no presenter notes.
- `director-notes.html`: off-screen presenter notes view.
- `director-cues.json`: machine-readable seven-scene timing and voiceover cues.
- `attestation.json`: hashed attestation, with no private signing key.
- `evidence/*.json`: compact evidence files for the truth matrix and demo
  counts.

Validation checks schema, file digests, mode consistency, fake-provider truth,
the visible mode badge, truth matrix rows, consistency fields, dashboard
required text, and secret-like bundle contents. A fake or fallback component
cannot be relabeled as live without failing validation.

`demo-serve` validates the bundle before serving and serves only files from the
bundle directory. `--check` prints the URL, file path, bundle digest, mode, and
truth status without starting the server.

`demo-director` also validates before serving. It writes only static director
assets inside the bundle directory, uses the bundle truth badge on every scene,
supports arrow/space/restart/escape controls, honors reduced-motion preferences,
and provides `director-record.html?duration=120&autoplay=1` as the clean
capture URL.

## Current Truth Boundary

The current winning bundle is mixed. It proves the core operation with
deterministic fallback providers, includes real local Hermes executable
evidence, and includes recorded-real prior Stripe sandbox full-transfer
evidence. It does not claim real Nemotron decisions, real OpenShell/NemoClaw
execution, real GitHub lifecycle writes, or a fresh real split Stripe Connect
Transfer.
