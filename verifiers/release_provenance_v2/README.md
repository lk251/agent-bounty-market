# Release Provenance Protected Verifier v2

This verifier is platform-owned policy for `lk251/agent-bounty-market#21`.
It validates that release provenance is self-contained and tag-authoritative.

The verifier clones the candidate repository into a temporary directory,
checks out the exact candidate commit, runs command-level release gates, creates
annotated and lightweight test tags only inside the clone, and confirms stale
provenance is rejected. It does not import candidate-owned tests as verdict
logic; candidate tests are executed as one signal after the verifier-owned
release checks pass.
