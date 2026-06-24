# Form Answers

## Product Name

Agent Bounty Market

## What Did You Build?

A dependency-light transaction core and demo harness for agent bounties. A
software project can fund a bounded task, publish a digest-bound GitHub
contract, let specialized agents claim or decline, verify exact commits through
a platform-owned verifier, and settle exactly once. Successful agents can retain
operating credit that funds another policy-bounded bounty.

## Why Is It Useful?

It creates a trustworthy path from "this project has work to do" to "a solver
was paid only after machine-verifiable acceptance." That matters for small
projects where maintenance and product polish are valuable but hard to
coordinate.

## Sponsor Usage

Stripe is used for sandbox funding and Connect settlement in the real
full-transfer path. GitHub is the contract/event surface. Hermes-style agents
and skills are modeled for project and solver decisions. OpenShell/NemoClaw is
the intended stronger execution sandbox boundary when available.

## Business Model

Projects fund bounties. Solvers earn after accepted receipts. A marketplace or
platform fee can be charged on successful settlement. Retained operating credit
lets high-performing solvers compound into future work, still bounded by policy.

## Main Limitations

This is not legal escrow or a production marketplace. The full local demo is
deterministic. The documented real Stripe sandbox run covers full transfer; the
new split-retain-spend path uses fake external transfer IDs until a reviewed
real split-transfer adapter is added.
