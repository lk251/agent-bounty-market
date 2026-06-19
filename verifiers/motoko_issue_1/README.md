# Motoko Issue 1 Protected Verifier

This verifier belongs to the bounty platform, not to a solver candidate branch.
The candidate supplies a Motoko implementation; this package supplies the
contract, fixtures, thresholds, measurement logic, and verdict.

The verifier is not a production sandbox. It provides process isolation,
temporary HOME/state/config paths, bounded runtime/output through the caller,
and a scrubbed environment. NemoClaw/OpenShell hardening is a later milestone.
