# Codex Session Handoff

HB2 prepared the issue #29 story/flywheel branch and pushed it for HB3 to finish
the release gate.

Branch:

```bash
git fetch origin
git switch codex/issue-29-story-flywheel
```

Implementation commits before this handoff document:

- `bfc5b96` - issue #29 story/flywheel implementation, regenerated bundle, and
  updated submission copy.
- `9da51ab` - HB2 native-Windows validation fixes.
- `341f962` - issue #29 release gate status in `submission/FINAL_HANDOFF.md`.

## What Is Done

- Pulled current `main` before starting; branch was created from
  `origin/main` at `5a3f559`.
- Read `docs/NEXT_CODEX_GOAL_STORY_FLYWHEEL.md` and issue #29.
- Reversed the deterministic settlement split:
  - reward: `$25.00`
  - solver wallet operating credit: `$20.00`
  - human/operator payout through the Stripe settlement path: `$5.00`
- Updated the demo story so the project agent buys verified work, the solver
  wallet controls the post-acceptance split, and the market-to-orchestrator data
  flywheel appears in scripts, Q&A, director scenes, dashboard text, tweets, and
  generated bundle assets.
- Preserved the visible `Mixed real/fallback` truth boundary.
- Rebuilt `demo/bundles/winning-run` from the available sanitized evidence.
- Updated HB2 native-Windows portability enough for the local Python suite and
  local demo checks to run.
- Pushed branch `codex/issue-29-story-flywheel` to `origin`.

## What Is Not Done

HB2 did not complete the issue #29 release gate. Do not close issue #29 until the
items below are finished.

- No immutable `hackathon-mixed-rc10` annotated tag has been created.
- No issue #29 completion comment has been posted.
- Issue #29 has not been closed.
- No pull request has been opened from this branch.
- The required Nix/Linux validation has not run on HB2 because native `nix` is
  not installed and no WSL distro is installed.
- The required fresh `demo-build-winning-run` command has not run on HB2 because
  the Motoko fixture checkout is not present here.
- `submission-check --entry --prepost` has not passed because
  `.demo/operator-submission.json` is not present on HB2.
- `release-audit --tag hackathon-mixed-rc10` has not passed because the tag does
  not exist yet.
- `nix flake check` has not run.

## HB2 Validation Already Run

These checks passed on HB2 native Windows:

```bash
python -m unittest discover -s tests
python -m py_compile <agent_bounty/verifiers/tests python files>
python -m agent_bounty submission-check
python -m agent_bounty submission-check --entry
python -m agent_bounty release-audit
python -m agent_bounty security-audit --quick
python -m agent_bounty demo-rehearse --mode replay --bundle demo/bundles/winning-run --repeat 5
python -m agent_bounty demo-director --bundle demo/bundles/winning-run --host 127.0.0.1 --port 8788 --duration 120 --check
git diff --check
```

Observed results:

- full native HB2 suite: `200 tests passed, 17 skipped`
- bundle digest:
  `sha256:1765bb2e57ed2e8c0d198591e6f52b77439f33266ca49fbaa02410f836dbedf4`
- attestation digest:
  `sha256:5c4703fc9c929198df97eae12a5d5c83310d736dd76edce64308f8a9eaba04d1`
- truth matrix digest:
  `sha256:a704f3e1a90d141c0f9c92bef2c4656cef92b5abf93bdeb1abfd9ed342530bc1`

The stale visible-copy proof search returned no matches across `README.md`,
`submission`, and `demo/bundles/winning-run`.

## HB3 Finish Steps

Run the issue #29 required gate on HB3/NixOS:

```bash
nix develop --command python3 -m unittest discover -s tests
nix develop --command python3 -m agent_bounty demo-build-winning-run \
  --db .demo/winning-run.sqlite3 \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency \
  --bundle demo/bundles/winning-run
nix develop --command python3 -m agent_bounty demo-director \
  --bundle demo/bundles/winning-run \
  --host 127.0.0.1 \
  --port 8788 \
  --duration 120 \
  --check
nix develop --command python3 -m agent_bounty demo-rehearse \
  --mode replay \
  --bundle demo/bundles/winning-run \
  --repeat 5
nix develop --command python3 -m agent_bounty submission-check --entry --prepost
nix develop --command python3 -m agent_bounty release-audit --tag hackathon-mixed-rc9 || true
nix flake check
git diff --check
```

If the regenerated bundle changes, commit those generated assets. Then, only
after all release checks pass, create the annotated rc10 tag using the canonical
message rendered by:

```bash
nix develop --command python3 -m agent_bounty release-provenance render-tag-message --tag hackathon-mixed-rc10
```

After the tag exists, run:

```bash
nix develop --command python3 -m agent_bounty release-audit --tag hackathon-mixed-rc10
```

Then push the branch and tag, comment on issue #29 with the commits, tag status,
split shown on screen, wording-replacement proof, validation results, and
recording instructions. Close issue #29 only after that completion gate is
satisfied.
