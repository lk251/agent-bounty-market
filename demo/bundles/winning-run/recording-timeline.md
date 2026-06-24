# Recording Timeline

Mode badge: `Mixed real/fallback`

Truth: `mixed-real-fallback`

## Two-Minute Cues

- `00:00` **Problem** — A real project has useful work that needs funding, verification, and settlement.
- `00:15` **Project buys work** — Budget and policy select one measurable Motoko TUI improvement.
- `00:35` **Agents choose** — Specialized agents decline or claim based on scope, capability, and margin.
- `00:55` **Trust boundary** — The protected verifier accepts only the exact candidate SHA and records a receipt.
- `01:20` **Settlement** — The reward is split into external transfer and retained operating credit.
- `01:45` **Compounding** — Retained credit funds the next bounded bounty without hiding fallback rows.
- `02:05` **Close** — Verified software work became operating capital.

## Truth Boundary

Keep the Mixed real/fallback badge visible. Name blocked and fallback components plainly.

## Fallbacks And Blockers

- **NVIDIA Nemotron model**: blocked — set AGENT_BOUNTY_RUN_HERMES_PROJECT_AGENT=1
- **Project-agent decision**: fallback — set AGENT_BOUNTY_RUN_HERMES_PROJECT_AGENT=1 for real Hermes project-agent runs
- **Solver-agent decision**: fallback — set AGENT_BOUNTY_RUN_HERMES_PROJECT_AGENT=1
- **OpenShell/NemoClaw execution**: blocked — docker executable not found on PATH
- **GitHub issue/claim/PR/result**: blocked — set AGENT_BOUNTY_GITHUB_INTEGRATION=1
- **Fresh split Stripe Connect Transfer**: blocked — set AGENT_BOUNTY_STRIPE_SANDBOX=1 for real Stripe sandbox commands
- **Retained credit funds second bounty**: fallback — fresh real split settlement is blocked; deterministic retained-credit spend is shown
