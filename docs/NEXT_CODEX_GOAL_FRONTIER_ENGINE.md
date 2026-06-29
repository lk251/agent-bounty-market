# Next Codex Goal — Frontier Engine story pass

Work in `/home/mares/repos/agent-bounty-market`.

Purpose: make the demo explicitly about the bigger mission: building a frontier-level open-source AI engine. Keep the current market demo, but add framing at the start and a stronger training-data flywheel visual near the end.

## Required changes

### 1. Add two opening scenes before the current market demo

**Opening Scene A**
- Title: `Building an Open Source Frontier Engine`
- Subtitle: `Frontier AI improves by learning from real work. Open source needs its own engine for generating high-quality agent data.`
- Bullets:
  - `Frontier AI needs more than models; it needs data and orchestration.`
  - `The hard part is getting high-signal trajectories instead of synthetic noise.`
  - `Open source needs a self-improving engine grounded in real work.`
- Narration target: `Our bigger goal is not just one bug fix. It is building an open-source frontier engine. Frontier AI improves by learning from real work, but open source lacks a clean, self-improving data engine for agentic tasks.`

**Opening Scene B**
- Title: `Agent Bounty Market is that data engine`
- Subtitle: `Project agents fund verified bounties. Specialist agents claim, solve, or decline them. Protected verifiers judge outcomes. Stripe records settlement. The whole loop becomes labeled data.`
- Visual: `Project budget -> Funded bounty -> Specialist agents -> Protected verifier -> Settlement`, with a line underneath: `All of it becomes training data.`
- Narration target: `Our thesis is that an agent labor market can become that engine. Project agents fund verified bounties, specialist agents decide whether to claim them, protected verifiers judge the work, and settlement records the economic outcome. That loop does not just improve software. It produces labeled agent data.`

### 2. Keep the current market demo concise

Preserve the strong middle section:
- Problem
- Project spends
- Agents choose
- Verification
- Settlement

Do not bloat it.

### 3. Add a stronger final training-data / flywheel scene before the close

Title: `One market, two learning loops`

Visual structure:
- Center box:
  - `Agent Bounty Market`
  - `Bounties • claims • declines • patches • verifier results • payouts`
- Left destination box:
  - `1. Worker-pool fast selector`
  - `Train on: who claimed or declined; which worker succeeded or failed; verifier pass/fail; cost / reward / margin`
  - `Output: Choose the right specialist worker faster`
- Right destination box:
  - `2. Frontier orchestrator training`
  - `Train on: full accepted paid trajectories; tool use + sequencing; repo context + patch path; verifier-confirmed outcomes`
  - `Output: Better end-to-end orchestrations`
- Feedback arrow / footer:
  - `Stronger project agents and stronger solver agents`
  - `Economic outcomes filter the data: paid verified work is high-signal.`

Narration target: `Here is the deeper flywheel. The market generates more than code. Claims and declines, verifier results, and cost-reward outcomes can train a fast selector that learns which specialist worker to route to which bounty. And the full accepted paid trajectories become high-quality examples for training stronger end-to-end orchestrators. Economic outcomes help filter the data: paid, verified work is high-signal.`

### 4. Strengthen the final close

Preferred close line:
`Agent Bounty Market turns open-source maintenance into a verified agent labor market — and a path toward a frontier-level open-source AI engine.`

Alternative:
`Agent Bounty Market is both a verified agent labor market and a data flywheel for building stronger open-source orchestrators.`

### 5. Keep the truth boundary

Keep the `Mixed real/fallback` badge visible. Do not fabricate live Stripe/Hermes/NVIDIA/OpenShell/GitHub behavior. The new opening and closing scenes are conceptual framing; the core market demo remains the evidence-backed center.

### 6. Files to update

At minimum update:
- `agent_bounty/demo_presentation.py`
- scene/timeline builders feeding `director-record.html` and `director-notes.html`
- `submission/DEMO_SCRIPT.md`
- `submission/VOICEOVER_FINAL.md`
- `submission/JUDGE_QA.md`
- regenerated `demo/bundles/winning-run/*`
- `submission/RECORDING_RUNBOOK.md` if duration changes
- `submission/FINAL_HANDOFF.md` if a new tag is created

### 7. Timing target

Keep the finished video around 2:20 to 2:45 and under 3 minutes.
Suggested structure:
- 0:00–0:12 — Opening Scene A
- 0:12–0:24 — Opening Scene B
- 0:24–0:40 — Problem
- 0:40–1:00 — Project spends
- 1:00–1:18 — Agents choose
- 1:18–1:43 — Verification
- 1:43–2:00 — Settlement
- 2:00–2:24 — Training Scene
- 2:24–2:36 — Close

### 8. Validation

Run:

```bash
nix develop --command python3 -m unittest discover -s tests
nix develop --command python3 -m agent_bounty demo-build-winning-run \
  --db .demo/winning-run.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency \
  --bundle demo/bundles/winning-run
nix develop --command python3 -m agent_bounty demo-director \
  --bundle demo/bundles/winning-run \
  --host 127.0.0.1 \
  --port 8788 \
  --duration 156 \
  --check
nix develop --command python3 -m agent_bounty demo-rehearse \
  --mode replay \
  --bundle demo/bundles/winning-run \
  --repeat 5
nix develop --command python3 -m agent_bounty submission-check --entry --prepost
nix flake check
git diff --check
```

If committed changes are made, create a new immutable annotated tag `hackathon-mixed-rc12`, update release docs, and run `nix develop --command python3 -m agent_bounty release-audit --tag hackathon-mixed-rc12`.

### Completion gate

Complete only when:
- the demo opens with the frontier-engine framing;
- the demo ends with a clear two-loop training/flywheel visual;
- the middle market demo remains concise and evidence-backed;
- the result still fits under 3 minutes;
- the final tag is release-audited if a new tag is created.
