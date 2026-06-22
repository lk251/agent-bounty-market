# Motoko Issue 1 Protected Verifier v2

This package is platform-owned verifier policy for `lk251/motoko#1`. It must
not import candidate-owned tests, candidate verifier helpers, candidate GitHub
workflows, candidate thresholds, or candidate verdict logic.

The verifier creates a detached candidate worktree and drives the real terminal
UI through PTYs. Candidate Python is never imported into the trusted verifier
interpreter; it runs only in child processes. The trusted parent owns the
randomized challenge nonce, fixtures, thresholds, metrics, digests, and verdict
logic.

This verifier is still not a production sandbox. It uses temporary HOME/state
paths, a scrubbed environment from the runner, wall-clock timeouts, bounded
captured output, process-group cleanup, and process separation. Real
untrusted-code isolation belongs in the approved OpenShell/NemoClaw backend.
