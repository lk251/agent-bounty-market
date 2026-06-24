# Specialized Solver Agents

Issue #3 adds the seller side of the market. Specialized solver profiles can
discover funded contracts, underwrite fit and economics, claim an exclusive
lease, execute through a bounded backend, submit evidence, and update capability
history only after protected verification.

## Runtime Truth

Default tests and demos use:

```text
fake-solver-agent-runtime-v1
deterministic-solver-underwriter-v1
local-isolated-process-fallback
```

Real Hermes/NemoClaw/Nemotron execution is not configured in this environment.
`solver-agent status` reports the exact blockers and does not label the fallback
as sponsor runtime execution.

```bash
python -m agent_bounty solver-agent status
```

Current blockers:

- install Hermes CLI or set `AGENT_BOUNTY_HERMES_CLI`;
- set `AGENT_BOUNTY_RUN_HERMES_PROJECT_AGENT=1`;
- set `AGENT_BOUNTY_HERMES_SOLVER_EVALUATE_COMMAND` to a reviewed solver
  wrapper;
- configure OpenShell/NemoClaw execution backend.

Issue #8 adds the role-specific solver wrapper and live decision demo:

```bash
python -m agent_bounty hermes-status
python -m agent_bounty hermes-solver-wrapper
python -m agent_bounty solver-agent evaluate --db .demo/solver.sqlite3 --runtime hermes
python -m agent_bounty demo-hermes-decisions --db .demo/hermes.sqlite3
```

See `docs/hermes-live-integration.md`.

## Profiles

The deterministic profile set contains:

- `solver_python_terminal_tui`: Python terminal/TUI and concurrency specialist;
- `solver_typescript_frontend`: TypeScript/frontend specialist;
- `solver_cuda_pytorch_perf`: CUDA/PyTorch performance specialist with explicit
  no-history uncertainty.

Capability records are empirical. They track attempts, accepted/rejected counts,
cost/time summaries, skill versions, task family, and settlement eligibility.
A profile with no history displays uncertainty instead of fabricated expertise.

## Skills

Versioned skills live in `skills/solver-agent/`:

- `funded-bounty-discovery`;
- `software-task-underwriter`;
- `python-terminal-responsiveness`;
- `protected-verifier-aware-pr`.

Skills are recorded by version and digest. Promotion requires an accepted
protected receipt and a regression fixture that does not make completeness,
policy compliance, or cost worse.

## Flow

Register profiles:

```bash
python -m agent_bounty solver-agent register-profiles --db .demo/solver.sqlite3
```

Discover funded contracts:

```bash
python -m agent_bounty solver-agent discover --db .demo/solver.sqlite3
```

Evaluate profile fit:

```bash
python -m agent_bounty solver-agent evaluate --db .demo/solver.sqlite3
```

Claim the trusted approved solver:

```bash
python -m agent_bounty solver-agent claim --db .demo/solver.sqlite3
```

Record deterministic Motoko replay execution:

```bash
python -m agent_bounty solver-agent execute --db .demo/solver.sqlite3
```

Submit and run protected verification:

```bash
python -m agent_bounty solver-agent submit \
  --db .demo/solver.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
```

Run the complete demo:

```bash
python -m agent_bounty demo-solver-motoko \
  --db .demo/solver.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
```

The demo shows multiple profiles, two capability/economic declines, one claim,
deterministic replay of the accepted Motoko issue #1 SHA, a PR evidence package,
protected verifier acceptance, exact-once capability update, and replay with no
duplicate claim/submission/receipt/capability earning.

## Safety

- Candidate-owned CI is not authoritative.
- The solver workspace never receives Stripe secrets, webhook secrets, broad
  GitHub credentials, SSH keys, personal Motoko state, or writable verifier
  source.
- Changed files are checked against allowed/forbidden path policy.
- PR evidence binds bounty/contract digest, solver profile version, base SHA,
  candidate SHA, changed files, commands, safe output digest, limitations,
  estimated cost, and verification receipt.
- PR head SHA must still match the verified candidate SHA before settlement.

## Live Solve Status

The real live-solve exit criterion remains incomplete. A local fallback row is
recorded as:

```text
mode = live-local-fallback
status = blocked
real_live_solve_complete = false
```

This is intentional until a reviewed safe live issue and real runtime/backend are
available.
