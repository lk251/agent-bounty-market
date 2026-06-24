name: protected-verifier-aware-pr
version: 0.1.0
category: solver-agent
provenance: agent-bounty-market issue-3

# Protected Verifier Aware PR

## Applicability

Use this skill when packaging a candidate patch for a trusted verifier.

## Required Evidence

- bounty/contract ID and digest;
- solver profile version;
- base and candidate SHAs;
- changed files;
- commands/tests run and output digests;
- verifier result or pending status.

## Stop Conditions

Do not include secrets, hidden tests, private prompts, or personal Motoko data.
Do not claim acceptance from candidate-owned CI.

## Commands Allowed

Trusted host may create commits, push branches, and open/update draft PRs
through the GitHub adapter. The solver workspace never receives broad push
credentials.

## Expected Output

A compact PR evidence section safe for public GitHub.
