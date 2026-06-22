# Motoko Issue 1 Protected Verifier v2

This package is platform-owned verifier policy for `lk251/motoko#1`. It must
not import candidate-owned tests, candidate verifier helpers, candidate GitHub
workflows, candidate thresholds, or candidate verdict logic.

The verifier creates a detached candidate worktree, imports only the candidate
Motoko implementation under test, and drives the real terminal UI through PTYs.
The background-study scenario runs the candidate Motoko executable in a separate
child process so whole-process scheduling stalls remain measurable.

This verifier is still not a production sandbox. It uses temporary HOME/state
paths, a scrubbed environment from the runner, wall-clock timeouts, bounded
captured output, and process separation. Real untrusted-code isolation belongs
to a later sandbox milestone.
