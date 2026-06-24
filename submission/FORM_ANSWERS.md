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

Stripe is used for sandbox funding and Connect settlement in the recorded real
full-transfer fragment and in the reviewed split-transfer adapter. GitHub is the
contract/event surface. Hermes-style agents and skills are modeled for project
and solver decisions, with a real Hermes executable present locally.
OpenShell/NemoClaw is the intended stronger execution sandbox boundary when
available.

## Business Model

Projects fund bounties. Solvers earn after accepted receipts. A marketplace or
platform fee can be charged on successful settlement. Retained operating credit
lets high-performing solvers compound into future work, still bounded by policy.

## Main Limitations

This is not a regulated custody product or a production marketplace. The
winning bundle is a validated `Mixed real/fallback` release candidate. The documented real Stripe
sandbox run covers full transfer; the reviewed split-retain-spend path still
needs loaded sandbox credentials to create a fresh real split Connect Transfer.
