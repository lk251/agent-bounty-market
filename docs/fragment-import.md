# Fragment Import

Authenticated fragments let an operator upgrade one component of the
`demo/bundles/winning-run` bundle without hand-editing JSON or changing code.
They preserve the mixed truth boundary: a component becomes `real` or
`recorded-real` only when the fragment validates.

## Commands

Validate a fragment:

```bash
nix develop --command python3 -m agent_bounty fragment validate \
  --file path/to/fragment.json \
  --bundle demo/bundles/winning-run
```

Import a fragment:

```bash
nix develop --command python3 -m agent_bounty fragment import \
  --bundle demo/bundles/winning-run \
  --file path/to/fragment.json
```

List imported fragments:

```bash
nix develop --command python3 -m agent_bounty fragment list \
  --bundle demo/bundles/winning-run
```

Rewrite a bundle from its imported fragments:

```bash
nix develop --command python3 -m agent_bounty fragment build-winning \
  --bundle demo/bundles/winning-run
```

Downgrades from `real` or `recorded-real` to `fallback` or `blocked` are
rejected by default. Use `--downgrade-ok` only when intentionally correcting bad
evidence.

## Schemas

Templates live in `demo/fragments/templates/`:

- `hermes-decision-fragment-v1.json`
- `nvidia-sandbox-fragment-v1.json`
- `github-lifecycle-fragment-v1.json`
- `stripe-split-settlement-fragment-v1.json`
- `motoko-verification-fragment-v1.json`

Each fragment contains:

- `schema`
- `component_id`
- `truth_status`
- `source_issue`
- `source_commit`
- `source_command`
- `captured_at`
- `source_digest`
- `safe_evidence`
- `evidence_digest`
- `consistency`
- `blocker`

`source_digest` is the SHA-256 digest of the safe source output, bundle, or
database evidence used to make the fragment. `evidence_digest` is the SHA-256
digest of canonical JSON for `safe_evidence`; the validator recomputes it and
rejects mismatches.

## Safe Evidence Only

Paste only safe IDs, URLs, counts, digests, and short status strings.

Do not paste:

- API keys, OAuth tokens, webhook secrets, or Link credentials;
- raw webhook payloads;
- Checkout URLs with client state;
- private prompts, tool traces, or chain of thought;
- personal Motoko documents or state;
- full logs containing secrets or private corpus content.

## Real-Evidence Rules

Real Stripe fragments require safe `cs_`, `pi_`, `ch_`, `evt_`, `acct_`, and
`tr_` IDs plus reconciliation evidence.

Real GitHub fragments require repository URL, issue number/URL, claim comment
ID/URL, PR number/URL, candidate SHA, and receipt publication ID/URL.

Real Hermes fragments require Hermes executable/version, provider/model ID,
skill digests, command digest, and strict JSON decision digest.

Real OpenShell/NemoClaw fragments require executable/version, sandbox or image
identity, policy digest, adversarial proof rows, and receipt backend binding.

Real Motoko verification fragments require candidate SHA, receipt ID, verifier
digest, backend digest, and metrics digest.

`fake_`, `local_`, `sim_`, and deterministic test IDs cannot appear in a `real`
fragment.

## Consistency

Fragments are checked against the target bundle. They must agree on project,
candidate SHA, currency, reward, and receipt ID when those fields are present.
Use secondary evidence only when the component is intentionally scoped away from
the primary bounty.

## Template Workflow

1. Copy one file from `demo/fragments/templates/`.
2. Replace every `REPLACE_...` placeholder.
3. Fill only safe evidence.
4. Compute `evidence_digest` over `safe_evidence`.
5. Run `fragment validate`.
6. Run `fragment import`.
7. Run `demo-rehearse --mode replay --repeat 5`.
8. Keep the dashboard badge honest.
