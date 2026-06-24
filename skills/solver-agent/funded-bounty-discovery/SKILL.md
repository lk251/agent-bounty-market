name: funded-bounty-discovery
version: 0.1.0
category: solver-agent
provenance: agent-bounty-market issue-3

# Funded Bounty Discovery

## Applicability

Use this skill when a solver profile searches open funded contracts it may be
qualified to claim.

## Required Evidence

- canonical bounty ID and contract digest;
- repository and issue reference;
- state, reward, currency, and base commit;
- verifier identity and task family.

## Stop Conditions

Stop when the contract is unfunded, stale, closed, unallowlisted, missing a
protected verifier, or outside the solver profile scope.

## Commands Allowed

Read-only market discovery commands only. Do not claim, edit, push, or spend.

## Expected Output

Return candidate bounty IDs with evidence refs and reasons to evaluate or
decline.
