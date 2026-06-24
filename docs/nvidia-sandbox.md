# NVIDIA OpenShell / NemoClaw Sandbox

Issue #9 adds the audited boundary for running Agent Bounty Market solver and
candidate verification work inside NVIDIA OpenShell or a NemoClaw-managed
OpenShell sandbox.

## Commands

Safe readiness report:

```bash
python -m agent_bounty nvidia-runtime-status
python -m agent_bounty nvidia-runtime-status --doctor --discover-models
```

Demo or truthful blocker:

```bash
python -m agent_bounty demo-nvidia-sandbox \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
```

Require a real OpenShell backend and fail instead of producing a fallback
bundle:

```bash
python -m agent_bounty demo-nvidia-sandbox \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency \
  --require-real
```

## Policy Artifacts

Project-owned OpenShell artifacts live under:

```text
nvidia/openshell/agent-bounty-policy.yaml
nvidia/openshell/manifest.json
nvidia/openshell/README.md
```

The policy is deny-by-default and describes the expected trust zones:

- trusted host orchestrator, GitHub/Stripe adapters, and receipt generation;
- sandboxed Hermes/solver workspace;
- untrusted candidate checkout inside the sandbox.

GitHub, Stripe, SSH, cloud, provider, and Motoko private state must not be
mounted into the sandbox. NVIDIA inference credentials are brokered host-side
and are never printed in status reports, bundles, traces, or issue comments.

## Current HB3 Blocker

At implementation time the host did not expose Docker or OpenShell in this
terminal environment. Therefore the current demo can produce a sanitized
fallback bundle with `real_backend=false`, but it must not claim a real
OpenShell/NemoClaw execution.

The expected real-host setup remains:

1. install Docker/OpenShell on an approved host;
2. create or select the approved `agent-bounty-verifier` sandbox;
3. confirm `python -m agent_bounty nvidia-runtime-status` has no blockers;
4. run `demo-nvidia-sandbox --require-real`;
5. verify the receipt records backend and policy digests.

## Official Source Evidence

Observed on 2026-06-24:

- OpenShell `main`: `2c545893ed247d4e04b585377d7bda8f24fd93dd`
- OpenShell `v0.0.38`: `dfd47683e7da4f1a4a8fa5d77f92d3696e6a41f9`
- OpenShell `v0.0.68`: `d64542f69d06694cbd203b64929d286dd0533bbb`
- NemoClaw `main`: `17d03317b042b56da8147a2e7d1955408c11d22d`
- `nemoclaw-community` `main`: `cea4ae01a0e2d7d359d37ed52b5bb454a226ca1b`
- OpenShell `install.sh` digest:
  `sha256:c15d6cb8090e1c7c8d79a320b5bcbdaf1c15c2363942d81e84b56e03b836249e`

Do not pipe remote installers directly into a shell. Download, inspect, record
the digest, and only then execute on an approved host.
