# Codex Instructions for Agent Bounty Market

This repository is the hackathon transaction core for an agent-native GitHub
bounty economy. It is deliberately separate from Motoko: Motoko is the first
fixture project, not the platform.

## Working Rules

- Use Python 3.12 and the standard library only unless Javier explicitly
  approves a dependency.
- Use integer minor currency units only. Never use floating point for money.
- Keep state transitions explicit, transactional, inspectable, and idempotent.
- Keep candidate repository code and platform-owned verifier policy on opposite
  sides of the trust boundary.
- Do not store secrets, credentials, SSH keys, provider tokens, or Stripe keys in
  this repository.
- Do not create remotes or push unless explicitly asked.

## Validation

Run before committing:

```bash
python3 -m unittest discover -s tests
python3 -m py_compile $(find agent_bounty verifiers tests -name '*.py' -print)
git diff --check
```
