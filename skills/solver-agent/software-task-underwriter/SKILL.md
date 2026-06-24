name: software-task-underwriter
version: 0.1.0
category: solver-agent
provenance: agent-bounty-market issue-3

# Software Task Underwriter

## Applicability

Use this skill when deciding whether a solver should claim a bounty.

## Required Evidence

- solver profile and verified history;
- reward, currency, and task class;
- estimated runtime/tool cost and completion time;
- risk flags and unknowns.

## Stop Conditions

Decline when capability is weak, expected margin is negative, operating budget
would be exceeded, or high-risk flags require human review.

## Commands Allowed

Read-only evaluation. Claiming is a host-side action after trusted policy
approval.

## Expected Output

Return `solver-bounty-decision-v1` with capability match, effort/cost estimate,
expected margin, plan, risks, unknowns, model, and skill versions.
