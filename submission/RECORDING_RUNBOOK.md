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
```

Expected:

- `ok=true`
- `mode=mixed`
- `truth_overall=mixed-real-fallback`
- dashboard path: `demo/bundles/winning-run/dashboard.html`

## Record

1. Open `demo/bundles/winning-run/dashboard.html`.
2. Keep the `Mixed real/fallback` badge visible in the opening shot.
3. Use the five dashboard cards as the story spine:
   - Project buys work
   - Agents choose
   - GitHub work
   - Trust
   - Economics compound
4. Show the blocker list briefly. Say that those components are not claimed as
   live in this bundle.
5. Close on: "Verified software work became operating capital."

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
