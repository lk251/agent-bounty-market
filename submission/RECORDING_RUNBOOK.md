# Recording Runbook

Goal: record the strongest truthful hackathon demo without implying that blocked
components ran live.

## Build And Validate

```bash
nix develop --command python3 -m agent_bounty demo-build-winning-run \
  --db .demo/winning-run.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency \
  --bundle demo/bundles/winning-run

nix develop --command python3 -m agent_bounty demo-rehearse \
  --mode replay \
  --bundle demo/bundles/winning-run \
  --repeat 5

nix develop --command python3 -m agent_bounty demo-serve \
  --bundle demo/bundles/winning-run \
  --host 127.0.0.1 \
  --port 8787 \
  --check
```

Expected:

- `ok=true`
- `mode=mixed`
- `truth_overall=mixed-real-fallback`
- dashboard path: `demo/bundles/winning-run/dashboard.html`
- serve URL: `http://127.0.0.1:8787/dashboard.html`
- recording cues: `demo/bundles/winning-run/recording-timeline.md`

## Serve

Start the local recording server:

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

1. Open `http://127.0.0.1:8787/dashboard.html`, or the local file
   `demo/bundles/winning-run/dashboard.html` as a backup.
2. Keep the `Mixed real/fallback` badge visible in the opening shot.
3. Use the five dashboard cards as the story spine:
   - Project buys work
   - Agents choose
   - GitHub work
   - Trust
   - Economics compound
4. Show the blocker list briefly. Say that those components are not claimed as
   live in this bundle.
5. Keep `demo/bundles/winning-run/recording-timeline.md` open as the timing
   script.
6. Close on: "Verified software work became operating capital."

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
