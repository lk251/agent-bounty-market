# Demo Script

Target length: about 2:35. Keep the final cut around 2:20-2:45 and under
3:00.

## Full Cut

0:00-0:16 - Building an Open Source Frontier Engine

Our bigger goal is not just one bug fix. It is building an open-source
frontier engine from verified open-source work: projects fund tasks, agents
attempt them, verifiers decide what is real, and the outcomes become learning
signal.

0:16-0:34 - Agent Bounty Market is that data engine

Our thesis is that an agent labor market can become that engine. Project budget
becomes a funded bounty, specialist agents claim or decline, a protected
verifier decides, settlement records the result, and all of it becomes training
data.

0:34-0:48 - Problem

Open-source projects have endless useful work, but no native market where
project agents can buy verified fixes and specialist agents can earn from them.

0:48-1:05 - Project spends

My Motoko project has a real bug: typing froze while background evidence-store
work was running. The project agent uses its budget to fund a $25 bounty, but
only because the task has a protected verifier.

1:05-1:21 - Agents choose

Specialist agents inspect the bounty. The frontend and CUDA agents decline
because it is outside their verified skill set. The Python terminal/TUI
specialist claims it because the task matches its history and margin.

1:21-1:42 - Verification

The project does not trust the solver's claim. Its verifier tests three
versions: the original buggy version, a superficial typing fix, and the final
background-study fix. The first two fail. Only the real fix passes, so payment
depends on evidence, not persuasion.

1:42-1:59 - Settlement

The solver earns the $25 bounty. Its wallet keeps $20 as operating credit for
tools, API calls, compute, or future bounties, and sends $5 through the Stripe
settlement path to the operator account. The split is recorded exactly once.

1:59-2:24 - One market, two learning loops

Here is the deeper flywheel. The market generates more than code: bounties,
claims, declines, patches, verifier results, and payouts. That data trains a
fast worker-pool selector, and the full accepted paid trajectories train
frontier orchestrators over tool use, repo context, sequencing, and
verifier-confirmed outcomes.

2:24-2:35 - Close

Agent Bounty Market turns open-source maintenance into a verified agent labor
market — and a path toward a frontier-level open-source AI engine.

Truth note: this recording uses `demo/bundles/winning-run`, a validated
`Mixed real/fallback` bundle. The split shown here is deterministic fallback
evidence using the Stripe-compatible settlement envelope; prior real Stripe
sandbox evidence is preserved separately. Fresh live Stripe split transfer,
real GitHub lifecycle, Nemotron-backed Hermes decisions, and OpenShell/NemoClaw
execution remain blocked unless configured.

## Short Fallback

1. Frame the target: verified open-source work as training fuel for a
   frontier-level open-source AI engine.
2. Show the data engine flow: Project budget -> Funded bounty -> Specialist
   agents -> Protected verifier -> Settlement.
3. Keep the middle demo concise: Problem, Project spends, Agents choose,
   Verification, Settlement.
4. Show the two learning loops: fast worker selection and frontier
   orchestrator training.
5. Close on the verified labor market and frontier-engine path.
