name: bounty-underwriter
version: 0.1.0
category: project-agent
provenance: agent-bounty-market issue-2

# Bounty Underwriter

## When It Applies

Use this skill after triage has identified a candidate that may be worth
funding.

## Inputs And Required Evidence

- candidate evidence and source;
- trusted policy digest;
- candidate issue class;
- protected verifier ID;
- reward hint or effort estimate;
- currency.

## Refusal Conditions

Decline when value is low, success cannot be verified, or effort/reward is
outside trusted policy. Return `needs_human` only when the task is otherwise
valid but policy requires review.

## Output Contract

Estimate user value, verifiability, solver effort, success probability, reward
in integer minor units, and risk flags. The estimate is a judgment with
provenance, not an objective probability.

## Budget And Safety

The skill may recommend a reward but must not modify policy, reserve funds, or
claim that payment is authorized.

## Example

A 60 minute bugfix with strong user impact and a protected verifier may justify
a small bounty within policy.

## Counterexample

A real bug with a proposed reward above `max_bounty_amount_cents` should be
flagged for trusted policy rejection, not silently funded.
