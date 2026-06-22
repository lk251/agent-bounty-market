# OpenShell Verifier Backend

The market has an execution backend interface with two implementations:

- `local-isolated-process`: default backend for deterministic local tests.
- `openshell`: adapter for an approved OpenShell sandbox named
  `agent-bounty-verifier`.

The local backend is intentionally limited. It uses scrubbed environment,
temporary HOME/state/work directories, a new process group, wall timeout,
bounded output, process-group kill, and Python resource limits where supported.
It is not a complete sandbox.

Official NVIDIA NemoClaw guidance says `nemoclaw <name> exec` is the preferred
managed one-off sandbox command, while `openshell sandbox exec` is the raw
OpenShell execution path. This repo exposes the lower-level `openshell` adapter
only as a verifier backend boundary; production deployment should decide whether
to wrap it with NemoClaw registry names or raw OpenShell sandbox names.

Inspect availability:

```bash
python -m agent_bounty openshell-status
```

Current HB3 result at implementation time:

```json
{"available":false,"backend":"openshell","blocker":"openshell executable not found on PATH"}
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
