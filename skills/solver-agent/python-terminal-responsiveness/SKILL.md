name: python-terminal-responsiveness
version: 0.1.0
category: solver-agent
provenance: agent-bounty-market issue-3

# Python Terminal Responsiveness

## Applicability

Use this skill for Python terminal/TUI latency, PTY handling, event loops,
background work, and responsiveness regressions.

## Required Evidence

- terminal/TUI code path;
- reproduction or protected verifier;
- base commit and candidate SHA;
- public commands or tests run.

## Stop Conditions

Stop if the task requires hidden verifier edits, personal state, unsupported
network access, or broad unrelated refactors.

## Commands Allowed

Repository-local read/edit/test commands within the allowed path policy. The
protected verifier source is read-only to the trusted host and not writable by
the solver.

## Expected Output

Produce a bounded plan, changed files, command evidence, safe output digests, and
limitations.
