# Final Handoff

Release candidate tag: `hackathon-mixed-rc12`

Truth status: `Mixed real/fallback`

Final commit SHA is intentionally not embedded in this committed file because
that would be self-referential; use `git rev-parse HEAD` after the rc12 commit.

## Story

Agent Bounty Market turns open-source maintenance into a verified agent labor
market — and a path toward a frontier-level open-source AI engine.

New scene order:

1. Building an Open Source Frontier Engine
2. Agent Bounty Market is that data engine
3. Problem
4. Project spends
5. Agents choose
6. Verification
7. Settlement
8. One market, two learning loops
9. Close

Total director duration: 155 seconds, about 2:35. This sits inside the target
2:20-2:45 range and under the 3:00 hard limit.

Recording URL:

```text
http://127.0.0.1:8788/director-record.html?duration=155&autoplay=1
```

Presenter notes URL:

```text
http://127.0.0.1:8788/director-notes.html
```

## Digests

Bundle digest:

```text
sha256:1fb0682c95a26283881b1e4fd54b5da3a6c6cabc74facf72209d64fe8531903d
```

Attestation digest:

```text
sha256:574d2bfad96894a63e7872b0f0b4d830069c85da091870974a795c1469eb328b
```

Truth matrix digest:

```text
sha256:6375530668244ab15891c0a89c1197e5847a1133766c7bdb55c601e4a4b98421
```

## Validation

HB2 Windows validation completed:

```bash
python -m unittest tests.test_demo_director tests.test_demo_presentation tests.test_submission_check tests.test_operator_submission tests.test_release_integrity
# 66 ran, 10 skipped; passed

python -m agent_bounty submission-check
# passed

python -m agent_bounty submission-check --entry
# passed

python -m agent_bounty demo-director --bundle demo/bundles/winning-run --host 127.0.0.1 --port 8788 --duration 155 --check
# passed; 9 scenes; record URL uses duration=155

python -m agent_bounty demo-rehearse --mode replay --bundle demo/bundles/winning-run --repeat 5
# passed; 5/5 validations

python -m agent_bounty release-audit
# passed before tag creation

python -m unittest discover -s tests
# 203 ran, 17 skipped; passed

git diff --check
# passed with Windows line-ending warnings only
```

Run this gate after the annotated tag exists:

```bash
python -m agent_bounty release-audit --tag hackathon-mixed-rc12
```

## Truth Boundary

The rc12 pass only changes story, generated presentation assets, and
release-facing documentation. It does not upgrade any blocked or fallback row
to live.

Not accomplished by rc12:

- No fresh live Stripe split transfer was run.
- No real GitHub issue/claim/PR/status lifecycle was run.
- No Nemotron-backed Hermes project/solver decision was run.
- No OpenShell/NemoClaw execution was run.
- No final social post, Typeform submission, or public video upload is included
  in the repo.

The `Mixed real/fallback` badge must stay visible in the recording.
