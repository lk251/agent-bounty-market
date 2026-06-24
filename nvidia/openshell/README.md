# Agent Bounty OpenShell Policy

This directory holds the project-owned policy and manifest for running Agent
Bounty Market solver and verifier work inside NVIDIA OpenShell or a
NemoClaw-managed OpenShell sandbox.

The policy is deny-by-default. GitHub and Stripe credentials stay on the host.
The sandbox receives only a sanitized task package, selected repository files,
public tests, solver profile data, and project-owned skills. Candidate code is
untrusted and should only write to its own worktree and ephemeral state.

## Status

Use the repo command:

```bash
python -m agent_bounty nvidia-runtime-status
```

It reports Docker, OpenShell, NemoClaw, policy, manifest, sandbox, and NVIDIA
credential readiness without printing secrets.

## Installation Discipline

Do not pipe remote installers directly into a shell. Download and inspect
OpenShell's installer first, record its digest, and only then run it on a host
where Docker/OpenShell is approved.

The current NVIDIA example still shows:

```bash
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | OPENSHELL_VERSION=v0.0.38 sh
```

This repository records the safer equivalent as an audited prerequisite, not as
an automatic setup step. System/NixOS service changes require operator approval.
