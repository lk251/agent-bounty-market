# Recording Timeline

Mode badge: `Mixed real/fallback`

Truth: `mixed-real-fallback`

## Two-Minute Cues

- `00:00` **Problem** — Open-source projects need a native market where project agents can buy verified fixes and specialist agents can earn from them.
- `00:15` **Project spends** — The project agent uses its budget to fund a $25 Motoko bounty because the task has a protected verifier.
- `00:35` **Agents choose** — Frontend and CUDA specialists decline; the Python terminal/TUI specialist claims the task because it matches history and margin.
- `00:55` **Verification** — The verifier rejects the original bug and superficial typing fix, then accepts only the final background-study fix.
- `01:20` **Settlement** — The solver earns $25; its wallet keeps $20 as operating credit and sends $5 through the Stripe settlement path to the operator account.
- `01:40` **Flywheel** — Every claim, decline, patch, verifier result, payout, and spend becomes high-quality training data for future orchestrators.
- `02:05` **Close** — Agent Bounty Market is a verified agent labor market and a data engine for better agent orchestration.

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
