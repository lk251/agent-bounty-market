# Release Checklist

Release tag: `hackathon-mixed-rc6`

Truth status: `Mixed real/fallback`.

## Required Commands

```bash
nix develop --command python3 -m agent_bounty demo-build-winning-run --db .demo/winning-run.sqlite3 --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency --bundle demo/bundles/winning-run
nix develop --command python3 -m agent_bounty submission-check
nix develop --command python3 -m agent_bounty release-audit
nix develop --command python3 -m agent_bounty demo-rehearse --mode replay --bundle demo/bundles/winning-run --repeat 5
nix develop --command python3 -m unittest discover -s tests
nix flake check
git diff --check
```

## Bundle

- [x] `demo/bundles/winning-run/manifest.json` exists.
- [x] `bundle.json`, `attestation.json`, `dashboard.html`, and `evidence/*.json`
  exist.
- [x] Manifest digests match bundle files.
- [x] Mode remains `mixed`.
- [x] Dashboard includes `Mixed real/fallback`.
- [x] Candidate SHA is
  `4c03e0fa02a26f1cbadbe593ae687eaa9b333d2c`.
- [x] Bundle has no secret-like strings or private `/home/...` paths.
- [x] Prior Stripe IDs remain in safe evidence fields only.

## Backup Bundle

Create a local ignored backup after validation:

```bash
nix develop --command python3 -m agent_bounty demo-build-winning-run --db .demo/release-backups/hackathon-mixed-rc6.sqlite3 --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency --bundle .demo/release-backups/hackathon-mixed-rc6
```

The backup lives under `.demo/`, which is ignored. Regenerate it from the
command above rather than committing generated databases.

## Known Live Blockers

- NVIDIA/Nemotron provider credentials are not configured.
- Docker/OpenShell/NemoClaw runtime is not available in this environment.
- Real GitHub integration token, repository, and webhook secret are not
  configured.
- Fresh split Stripe Connect Transfer is blocked until sandbox env and CLI
  webhook secret are loaded.

## Recording

```bash
nix develop --command python3 -m agent_bounty demo-serve --bundle demo/bundles/winning-run --host 127.0.0.1 --port 8787
```

Record `http://127.0.0.1:8787/dashboard.html`, keep the `Mixed real/fallback`
badge visible, and use `submission/RECORDING_RUNBOOK.md` plus
`submission/DEMO_SCRIPT_90S.md` or `submission/DEMO_SCRIPT_3MIN.md`.
