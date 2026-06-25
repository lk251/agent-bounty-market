# Recording Runbook

Goal: record the strongest truthful hackathon demo without implying that blocked
components ran live.

Release tag: `hackathon-mixed-rc9`.

## Build And Validate

```bash
nix develop --command python3 -m agent_bounty demo-build-winning-run \
  --db .demo/winning-run.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency \
  --bundle demo/bundles/winning-run

nix develop --command python3 -m agent_bounty submission-check

nix develop --command python3 -m agent_bounty demo-rehearse \
  --mode replay \
  --bundle demo/bundles/winning-run \
  --repeat 5

nix develop --command python3 -m agent_bounty demo-serve \
  --bundle demo/bundles/winning-run \
  --host 127.0.0.1 \
  --port 8787 \
  --check

nix develop --command python3 -m agent_bounty demo-director \
  --bundle demo/bundles/winning-run \
  --host 127.0.0.1 \
  --port 8788 \
  --duration 120 \
  --check
```

Expected:

- `ok=true`
- `mode=mixed`
- `truth_overall=mixed-real-fallback`
- dashboard path: `demo/bundles/winning-run/dashboard.html`
- serve URL: `http://127.0.0.1:8787/dashboard.html`
- director URL: `http://127.0.0.1:8788/director.html?duration=120`
- record URL: `http://127.0.0.1:8788/director-record.html?duration=120&autoplay=1`
- recording cues: `demo/bundles/winning-run/recording-timeline.md`
- director cues: `demo/bundles/winning-run/director-cues.json`

## Serve

Start the local recording server:

```bash
nix develop --command python3 -m agent_bounty demo-director \
  --bundle demo/bundles/winning-run \
  --host 127.0.0.1 \
  --port 8788 \
  --duration 120
```

The command validates the bundle, generates `director.html`,
`director-record.html`, `director-notes.html`, and `director-cues.json`, then
serves only files from the bundle directory.

Fallback dashboard server:

```bash
nix develop --command python3 -m agent_bounty demo-serve \
  --bundle demo/bundles/winning-run \
  --host 127.0.0.1 \
  --port 8787
```

The command validates the bundle before serving. If the bundle is tampered, it
prints validation mismatches and exits nonzero instead of serving. It serves
only files from the bundle directory.

## Record

1. Open `http://127.0.0.1:8788/director-record.html?duration=120&autoplay=1`
   for capture. Keep `http://127.0.0.1:8788/director-notes.html` off-screen as
   the presenter notes view.
2. Keep the `Mixed real/fallback` badge visible in the opening shot.
3. Use the seven director scenes as the story spine:
   - Problem
   - Project buys work
   - Agents choose
   - Trust boundary
   - Settlement
   - Compounding
   - Close
4. In the Trust boundary scene, call out the three Motoko verifier outcomes:
   baseline rejected, idle-only rejected, final accepted.
5. In the Compounding scene, call out issue #21 as retained-credit dogfood for
   release provenance: candidate, receipt, verifier digest, and replay evidence.
6. Show the blocker/fallback statements briefly. Say that those components are
   not claimed as live in this bundle.
7. Use `submission/VOICEOVER_FINAL.md` as the spoken script and
   `demo/bundles/winning-run/director-cues.json` as the timing source.
8. Close on: "Verified software work became operating capital."

## Screenshot

The current Nix shell does not include a headless browser or image stack. Use a
manual screenshot:

1. Open the served dashboard in a browser.
2. Set browser zoom to 100%, then verify 110% and 125% remain readable.
3. Use a 1920x1080 window when possible.
4. Capture the full first viewport with the mode badge and five cards visible.
5. Do not crop out the fallback/blocker section if using the image as a
   thumbnail.

## Voiceover Boundary

Use this exact framing if time allows:

```text
This is a mixed real/fallback release candidate. Hermes itself is installed and
verified locally, and prior real Stripe sandbox transfer evidence is preserved.
The full live Nemotron, OpenShell, GitHub, and fresh split-Stripe paths are
blocked by missing external runtime or credentials, so they remain visibly
marked as blocked or fallback.
```

## Do Not Say

- Do not say the full demo is live.
- Do not say the fresh split Stripe transfer ran unless a real `tr_...` object
  appears in the new split path.
- Do not say GitHub issue/claim/PR/status lifecycle ran unless the GitHub row is
  `real`.
- Do not crop out the mode badge.
- Do not show `.env`, raw webhook payloads, API keys, or private logs.
