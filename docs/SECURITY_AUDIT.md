# Security Audit

This document records the issue #22 adversarial audit of the trusted kernel for
the Agent Bounty Market hackathon release.

## Scope

Audited trust boundaries:

- money ledger, account balances, reservations, settlement allocation, retained
  operating credit, and idempotency;
- protected verification receipts, candidate/base binding, verifier digest
  binding, and payout gates;
- Stripe webhook signature handling and event recording;
- GitHub issue/claim/submission marker parsing;
- authenticated evidence fragments and downgrade protection;
- release bundle validation, replay, manifest binding, and annotated tag
  provenance;
- local execution boundaries around protected verifier and demo commands;
- current tree and optional recent Git history for secret-like values.

Out of scope:

- live Stripe object correctness beyond sandbox adapter/status checks;
- real GitHub webhook delivery beyond recorded-event validation;
- external Hermes, NVIDIA, OpenShell, or Motoko runtime behavior;
- operating-system hardening outside this repository.

## Methodology

The audit treats comments, docs, fake clients, evidence fragments, release
bundles, webhook payloads, candidate-owned files, and candidate-owned tests as
untrusted. The harness intentionally combines:

- deterministic randomized model checks over market state transitions;
- mutation probes that attempt common trust-boundary bypasses;
- malformed-input fuzz probes for marker parsers, fragments, Stripe signature
  parsing, and release provenance;
- filesystem probes for bundle path traversal and symlink escape;
- release audit reuse for bundle, manifest, truth-matrix, and tag binding;
- content-safe secret scanning that reports kind, path, line, and digest only.

Primary commands:

```bash
nix develop --command python3 -m agent_bounty security-audit --quick
nix develop --command python3 -m agent_bounty security-audit --full
```

`--quick` is bounded for CI and issue handoff. `--full` increases randomized
state coverage and scans recent Git history.

## Invariants

| Area | Invariants |
| --- | --- |
| Money | Minor-unit integers; currency consistency; nonnegative trusted accounts; settlement split sums; exactly-once idempotency. |
| Verification | Candidate/base binding; verifier digest binding; accepted receipt gates settlement; verifier errors/timeouts never pay. |
| External events | Stripe raw-body signature verification; GitHub delivery dedupe; changed idempotency parameters fail; out-of-order events stay recorded. |
| Execution | Scrubbed environments; bounded output/time; platform-owned verifier path; shell-free subprocess construction. |
| Evidence release | Fragment downgrade protection; fake IDs rejected in real rows; bundle digest binding; annotated tag provenance. |

## Findings

### ABM-SEC-001: Bundle Validation Path Escape

- Severity: P1.
- Status: fixed.
- Affected boundary: release bundle validation and scanners.
- Issue: bundle manifest entries were resolved by joining paths, and bundle
  secret/private-path scanners in both bundle validation and release audit
  walked symlink targets without first proving the resolved file stayed under
  the bundle root.
- Risk: a malicious or malformed local bundle could cause validation to touch
  files outside the bundle. The released scanners did not print file contents,
  but touching out-of-bundle files is still an unsafe validation boundary.
- Fix: manifest paths are now rejected if absolute, if they contain `..`, or if
  their resolved target escapes the bundle root. Bundle scanner paths are now
  resolved before read in both validation and release audit, and symlink escapes
  are reported as mismatches.
- Reproduction/tests:

```bash
nix develop --command python3 -m unittest tests.test_demo_presentation
nix develop --command python3 -m agent_bounty security-audit --quick
```

Regression tests:

- `test_bundle_manifest_refuses_paths_outside_bundle`
- `test_bundle_scanners_refuse_symlink_escape`
- `test_release_audit_refuses_manifest_path_escape`
- `test_release_audit_refuses_symlink_escape`

## Mutation Score

Current harness probes:

1. duplicate settlement replay does not alter ledger;
2. rejected work cannot settle;
3. unfunded reserve cannot create a negative trusted balance;
4. changed idempotency arguments are denied;
5. verification receipt binds candidate commit;
6. invalid Stripe signature is denied;
7. real evidence fragment with fake/local ID is denied;
8. fragment downgrade from recorded-real to fallback is denied;
9. bundle manifest path escape is denied;
10. release tag digest mismatch is denied.

Current quick result: `10/10` probes passed.

## Randomized And Fuzz Coverage

Quick mode:

- randomized model check: 8 seeds, 20 operations per seed;
- malformed-input fuzz: 40 cases.

Full mode:

- randomized model check: 40 seeds, 50 operations per seed;
- malformed-input fuzz: 200 cases;
- recent Git history secret scan enabled.

The model checker recomputes account balances independently from ledger entries
and rechecks settlement and receipt invariants after each randomized operation.

## Secret And Privacy Audit

The scanner looks for real-looking Stripe secret keys, Stripe webhook secrets,
GitHub tokens, NVIDIA API keys, private keys, and Stripe Checkout URLs. It also
warns on private path strings. Findings are content-safe: they include only
kind, severity, path, line, optional commit, and a SHA-256 digest of the matched
value.

Private path warnings are expected in docs and tests because this release names
local demo paths such as `/home/mares/repos/...`. Those warnings are not release
blockers. Any `fail` severity hit is a P0 release blocker requiring operator
rotation and explicit follow-up.

## Residual Risk

- The released bundle remains operator-provided local input, so validation must
  continue to fail closed on path, digest, truth, and provenance mismatches.
- Fake-provider and fallback evidence remain intentionally marked as fake or
  blocked; they must never be promoted to real runtime evidence without an
  authenticated fragment and release-provenance update.
- The audit harness does not prove external service availability. It verifies
  the local trusted kernel around those integrations.

## Release Recommendation

Release recommendation is `pass` when:

- `security-audit --quick` passes;
- `security-audit --full` passes;
- release audit passes;
- no open P0/P1 findings remain;
- all confirmed P0/P1 fixes have regression coverage.

As of the issue #22 audit implementation, `ABM-SEC-001` is fixed with
regression coverage, the quick audit passes, and the command output is the
source of truth for the exact commit and full-mode result.
