# Hermes Project-Agent Buyer

Issue #2 adds a bounded project-agent buyer around the trusted market kernel.
The agent proposes; trusted code decides whether anything can spend.

## Source Inspection

Current sponsor/runtime sources inspected before implementation:

- Nous Research Hermes Agent repository and docs: skill/memory/learning loop,
  model-provider flexibility, terminal/tool interface.
- Hermes Skills System docs: skills are on-demand knowledge documents using
  progressive disclosure and normally live under `~/.hermes/skills/`.
- NVIDIA NemoClaw docs and repository: NemoClaw runs agents such as Hermes more
  safely inside NVIDIA OpenShell sandboxes with routed inference and lifecycle
  management.
- NVIDIA Nemotron docs: Nemotron is the promoted NVIDIA model family for
  long-running, self-evolving agent workflows and includes reasoning/retrieval
  model options.

Recorded URLs:

- `https://github.com/NousResearch/hermes-agent`
- `https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/skills.md`
- `https://docs.nvidia.com/nemoclaw/user-guide/openclaw/home`
- `https://github.com/NVIDIA/NemoClaw`
- `https://www.nvidia.com/en-us/ai-data-science/foundation-models/nemotron/`

## Runtime Boundary

Two runtimes exist:

- `fake-project-agent-runtime-v1`: deterministic, dependency-free runtime used
  by default tests and demos.
- `hermes-cli-adapter-v1`: gated adapter for a reviewed Hermes wrapper command
  that reads one JSON request from stdin and returns structured JSON.

The Hermes adapter does not receive Stripe or GitHub credentials. It runs with a
scrubbed environment containing only `HOME`, `PATH`, `HERMES_HOME`, and
`AGENT_BOUNTY_PROJECT_AGENT=1`.

Readiness:

```bash
python -m agent_bounty project-agent status
```

Real Hermes execution requires:

```text
AGENT_BOUNTY_RUN_HERMES_PROJECT_AGENT=1
AGENT_BOUNTY_HERMES_PROJECT_EVALUATE_COMMAND=<reviewed project wrapper command>
Hermes CLI installed or AGENT_BOUNTY_HERMES_CLI set
```

The default status currently reports this as blocked. The demo therefore
truthfully reports the fake runtime and does not claim Hermes, NemoClaw, or
Nemotron ran.

Issue #8 adds a dedicated live status and wrapper surface:

```bash
python -m agent_bounty hermes-status
python -m agent_bounty hermes-install-skills
python -m agent_bounty hermes-project-wrapper
python -m agent_bounty demo-hermes-decisions --db .demo/hermes.sqlite3
```

See `docs/hermes-live-integration.md`.

## Skills

Versioned skills live in `skills/project-agent/`:

- `project-bounty-triage`
- `bounty-underwriter`
- `acceptance-contract-author`

Each skill records when it applies, required evidence, refusal conditions,
output schema, budget/safety boundary, examples, counterexamples, version, and
provenance. Skill metadata and digests are persisted into SQLite for each run.

To use them with Hermes, copy or symlink the skill directories into the relevant
Hermes profile, for example:

```bash
mkdir -p ~/.hermes/skills/agent-bounty-market
cp -R skills/project-agent/* ~/.hermes/skills/agent-bounty-market/
```

Restore by repeating the copy from the repository. Do not promote edited skills
without review or measured improvement.

## Candidate Intake

The current candidate queue is deterministic and allowlisted. It models the
four required demo candidates:

1. Motoko issue #1, a measurable TUI background-study latency bug with a
   protected verifier.
2. A broad subjective refactor, declined as vague.
3. A measurable task with a reward above trusted policy, declined by policy.
4. A potentially useful task with no protected verifier, declined until scoped.

Future GitHub-native intake should add real issue/check/problem-report sources
through the issue #1 GitHub event spine without allowing arbitrary repo crawling.

## Trusted Policy

`project-agent-policy-v1` is loaded by trusted code, never from agent output.
It enforces:

- maximum bounty amount;
- monthly/period budget field;
- minimum remaining reserve;
- allowed repositories, issue classes, verifier IDs, and currencies;
- human approval threshold;
- maximum simultaneous bounties;
- minimum acceptance-contract fields;
- agent runtime budget metadata.

Publication failure policy is explicit:

```text
retain_reserved_for_retry
```

If GitHub publication fails after reservation, funds stay reserved for a safe
retry. The retry path is idempotent and does not reserve twice.

## Commands

Scan candidates and save trusted policy:

```bash
python -m agent_bounty project-agent scan --db .demo/project-agent.sqlite3
```

Evaluate with the fake runtime:

```bash
python -m agent_bounty project-agent evaluate --db .demo/project-agent.sqlite3 --runtime fake
```

Reserve and publish with fake GitHub:

```bash
python -m agent_bounty project-agent fund-and-publish \
  --db .demo/project-agent.sqlite3 \
  --fake-github
```

Run the complete issue #2 demo:

```bash
python -m agent_bounty demo-project-agent-motoko --db .demo/project-agent.sqlite3
```

The demo shows treasury/policy, four candidates, one approval, three
declines/policy gates, exact reservation, fake GitHub publication, contract
digest, and replay with no duplicate reservation/publication.
