# OpenShell Verifier Backend

The market has an execution backend interface with two implementations:

- `local-isolated-process`: default backend for deterministic local tests.
- `openshell`: adapter for an approved OpenShell sandbox named
  `agent-bounty-verifier`.

The local backend is intentionally limited. It uses scrubbed environment,
temporary HOME/state/work directories, a new process group, wall timeout,
bounded output, process-group kill, and Python resource limits where supported
for CPU, address space, file size, open files, and process count. It is not a
complete sandbox.

Official NVIDIA NemoClaw guidance says `nemoclaw <name> exec` is the preferred
managed one-off sandbox command, while `openshell sandbox exec` is the raw
OpenShell execution path. This repo exposes the lower-level `openshell` adapter
only as a verifier backend boundary; production deployment should decide whether
to wrap it with NemoClaw registry names or raw OpenShell sandbox names.

The current OpenShell policy artifact is
`nvidia/openshell/agent-bounty-policy.yaml`; the older verifier-local policy is
kept as a compatibility fallback. The project policy declares deny-by-default
network behavior and no candidate-visible credentials. The status commands hash
that file into `policy_digest`.

Inspect availability:

```bash
python -m agent_bounty openshell-status
python -m agent_bounty nvidia-runtime-status
python -m agent_bounty demo-nvidia-sandbox \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
```

Current HB3 result at implementation time:

```json
{"available":false,"backend":"openshell","backend_digest":"sha256:de5fea9ab2881a2476b81285f4c8beac09541227aa90a08b9f155abb47b861f9","blocker":"openshell executable not found on PATH","policy_digest":"sha256:8cd342225854dda399c88c52ec0a37485dd4f8c376d24414c89a4ec6952e2914","sandbox":"agent-bounty-verifier","schema":"openshell-backend-status-v1"}
```

The status output also includes `backend_digest` and `policy_digest` so a
verifier receipt can record exactly which backend policy was intended.

When OpenShell is installed and an approved sandbox is present, the backend must
keep these invariants:

- no verifier credentials or parent env secrets inside the candidate sandbox;
- deny-by-default network policy unless a platform owner explicitly grants an
  endpoint;
- candidate checkout mounted or copied as untrusted input only;
- parent-owned verifier policy and receipt generation outside candidate control;
- stdout/stderr treated as observation data, never authoritative acceptance.
