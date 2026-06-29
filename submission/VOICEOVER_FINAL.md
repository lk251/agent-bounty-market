# Final Voiceover

Release tag: `hackathon-mixed-rc12`.

Target length: 155 seconds, about 2:35. Keep the visible `Mixed real/fallback`
truth badge in frame throughout.

## Script

Our bigger goal is not just one bug fix. It is building an open-source
frontier engine from verified open-source work: projects fund tasks, agents
attempt them, verifiers decide what is real, and the outcomes become learning
signal.

Our thesis is that an agent labor market can become that engine. Project budget
becomes a funded bounty, specialist agents claim or decline, a protected
verifier decides, settlement records the result, and all of it becomes training
data.

Open-source projects have endless useful work, but no native market where
project agents can buy verified fixes and specialist agents can earn from them.

My Motoko project has a real bug: typing froze while background evidence-store
work was running. The project agent uses its budget to fund a $25 bounty, but
only because the task has a protected verifier.

Specialist agents inspect the bounty. The frontend and CUDA agents decline
because it is outside their verified skill set. The Python terminal/TUI
specialist claims it because the task matches its history and margin.

The project does not trust the solver's claim. Its verifier tests three
versions: the original buggy version, a superficial typing fix, and the final
background-study fix. The first two fail. Only the real fix passes, so payment
depends on evidence, not persuasion.

The solver earns the $25 bounty. Its wallet keeps $20 as operating credit for
tools, API calls, compute, or future bounties, and sends $5 through the Stripe
settlement path to the operator account. The split is recorded exactly once.

Here is the deeper flywheel. The market generates more than code: bounties,
claims, declines, patches, verifier results, and payouts. That data trains a
fast worker-pool selector, and the full accepted paid trajectories train
frontier orchestrators over tool use, repo context, sequencing, and
verifier-confirmed outcomes.

This demo is intentionally labeled Mixed real/fallback. Real and recorded-real
evidence stay visible, and blocked sponsor paths stay blocked instead of being
claimed as live.

## One-Line Close

Agent Bounty Market turns open-source maintenance into a verified agent labor
market — and a path toward a frontier-level open-source AI engine.
