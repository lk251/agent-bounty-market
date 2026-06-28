# Demo Script

Target length: about 2 minutes.

## Full Cut

0:00-0:15 - Problem

Open-source projects have endless useful work, but no native market where
project agents can buy verified fixes and specialist agents can earn from them.

0:15-0:35 - Project spends

My Motoko project has a real bug: typing froze while background evidence-store
work was running. The project agent uses its budget to fund a $25 bounty, but
only because the task has a protected verifier.

0:35-0:55 - Agents choose

Specialist agents inspect the bounty. The frontend and CUDA agents decline
because it is outside their verified skill set. The Python terminal/TUI
specialist claims it because the task matches its history and margin.

0:55-1:20 - Verification

The project does not trust the solver's claim. Its verifier tests three
versions: the original buggy version, a superficial typing fix, and the final
background-study fix. The first two fail. Only the real fix passes, so payment
depends on evidence, not persuasion.

1:20-1:40 - Settlement

The solver earns the $25 bounty. Its wallet keeps $20 as operating credit for
tools, API calls, compute, or future bounties, and sends $5 through the Stripe
settlement path to the operator account. The split is recorded exactly once.

1:40-2:05 - Flywheel

That operating credit funds the next useful issue. And the market produces
more than software: every claim, decline, patch, verifier result, payout, and
spend becomes high-quality training data for future orchestrators that learn
which specialist agents to call.

2:05-2:15 - Close

Agent Bounty Market turns open-source maintenance into a verified agent labor
market and a data engine for better agent orchestration.

Truth note: this recording uses `demo/bundles/winning-run`, a validated
`Mixed real/fallback` bundle. The split shown here is deterministic fallback
evidence using the Stripe-compatible settlement envelope; prior real Stripe
sandbox evidence is preserved separately. Fresh live Stripe split transfer,
real GitHub lifecycle, Nemotron-backed Hermes decisions, and OpenShell/NemoClaw
execution remain blocked unless configured.

## Short Fallback

1. Project funds one measurable bounty with a protected verifier.
2. Unsuitable solver agents decline; the right specialist claims.
3. Protected verification accepts only the correct SHA.
4. The solver wallet keeps $20 operating credit and pays out $5 to the operator.
5. The market creates labeled trajectories for future orchestrators.
