# Hermes Live Integration

Issue #8 adds the reviewed boundary for real Hermes Agent and NVIDIA Nemotron
decision runs. The default local demo still remains deterministic unless every
live gate is configured.

## Sources Checked

- Hermes Quickstart:
  `https://hermes-agent.nousresearch.com/docs/getting-started/quickstart`
- Hermes Skills System:
  `https://hermes-agent.nousresearch.com/docs/user-guide/features/skills`
- NVIDIA Hermes/NemoClaw blog:
  `https://developer.nvidia.com/blog/deploy-self-evolving-agents-for-faster-more-secure-research-with-a-hermes-agent-and-nvidia-nemoclaw/`
- NemoClaw repository:
  `https://github.com/NVIDIA/NemoClaw`

Relevant constraints from those sources:

- Hermes CLI install is normally `curl -fsSL .../install.sh | bash`, but this
  repo never pipes remote scripts directly. Download, inspect, then run.
- Hermes requires a model with at least 64K context.
- NVIDIA NIM is configured through `NVIDIA_API_KEY` and optional
  `NVIDIA_BASE_URL`.
- Skills live under `~/.hermes/skills/`, and external/project-owned skills can
  be installed under their own namespace.

## Current HB3 Status

Hermes CLI is installed and executable at:

```text
/home/mares/.local/bin/hermes
```

Observed version:

```text
Hermes Agent v0.17.0 (2026.6.19) · upstream 9259d1e5
```

The official installer was downloaded and inspected. The observed installer
digest was:

```text
sha256:975e525aa420db1ec49b1ba0d6012682edf68224322656a68b87b17655bc38a2
```

The first direct installer attempt failed on NixOS because downloaded generic
Linux `uv` and CPython binaries could not run. The successful user-owned path
used Nix-provided `uv`, `python3.11`, and `nodejs_22` on `PATH`, then ran:

```bash
bash install.sh --skip-setup --skip-browser --no-skills --non-interactive
```

The installer completed the Hermes launcher but could not append to
`/home/mares/.bashrc` because that file is a Home Manager symlink into
`/nix/store`. This is harmless for this repo: call
`/home/mares/.local/bin/hermes` directly or set `AGENT_BOUNTY_HERMES_CLI`.

Current exact live blocker:

```text
NVIDIA_API_KEY is not present, so `hermes-status --discover-models` cannot query
NVIDIA NIM `/v1/models` and cannot record an exact Nemotron model ID.
```

The project-owned skills were still installed idempotently to:

```text
/home/mares/.hermes/skills/agent-bounty-market
```

## Commands

Safe status:

```bash
python -m agent_bounty hermes-status
python -m agent_bounty hermes-status --doctor --discover-models
```

Skill manifest and install:

```bash
python -m agent_bounty hermes-install-skills --dry-run
python -m agent_bounty hermes-install-skills
```

Reviewed wrapper commands:

```bash
python -m agent_bounty hermes-project-wrapper
python -m agent_bounty hermes-solver-wrapper
```

Decision demo:

```bash
python -m agent_bounty demo-hermes-decisions \
  --db .demo/hermes.sqlite3 \
  --bundle .demo/bundles/hermes-decisions
```

Require a real run and fail instead of falling back:

```bash
python -m agent_bounty demo-hermes-decisions \
  --db .demo/hermes.sqlite3 \
  --bundle .demo/bundles/hermes-decisions \
  --require-real
```

## Live Configuration Gates

Set these only in trusted local environment/config, never in commits, issue
comments, bundles, traces, or candidate workspaces:

```text
AGENT_BOUNTY_RUN_HERMES_PROJECT_AGENT=1
AGENT_BOUNTY_HERMES_CLI=/path/to/hermes
AGENT_BOUNTY_HERMES_CONTEXT_TOKENS=64000
AGENT_BOUNTY_NVIDIA_MODEL_ID=<discovered safe model id>
NVIDIA_API_KEY=<secret>
NVIDIA_BASE_URL=<optional endpoint>
```

Role-specific reviewed wrappers:

```text
AGENT_BOUNTY_HERMES_PROJECT_EVALUATE_COMMAND="python -m agent_bounty hermes-project-wrapper"
AGENT_BOUNTY_HERMES_SOLVER_EVALUATE_COMMAND="python -m agent_bounty hermes-solver-wrapper"
```

Legacy `AGENT_BOUNTY_HERMES_EVALUATE_COMMAND` still works as a fallback, but
the issue #8 boundary prefers separate project and solver wrappers.

## Security Boundary

Hermes proposes structured JSON only. Trusted host code remains authoritative
for:

- policy;
- money and reservations;
- GitHub writes;
- claim leases;
- verification receipts;
- settlement.

The wrappers use a scrubbed environment and do not pass Stripe keys, GitHub
tokens, webhook secrets, SSH material, Motoko personal state, or broad project
state into Hermes.

Wrapper output must be exactly one JSON object. Markdown, prose wrappers,
trailing data, malformed JSON, schema drift, or nonzero exit fail closed.

## Truth Labels

`demo-hermes-decisions` emits:

- `real_runtime=true` only when Hermes CLI, wrappers, provider, model, context,
  and run gates are configured;
- `nemotron_real=true` only when NVIDIA credentials/model gates are configured;
- fallback decisions with deterministic runtime names when any live gate is
  missing.

A fallback bundle is useful for recording structure, but it is not live Hermes
or live Nemotron evidence.
