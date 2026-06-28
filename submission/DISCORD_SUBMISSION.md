# Discord Submission

Status: draft until `[FINAL_TWEET_URL]` is filled.

## Concise Version

```text
Agent Bounty Market

Tweet/video: [FINAL_TWEET_URL]
Repository: [REPO_URL]
Release tag: hackathon-mixed-rc10
Truth label: Mixed real/fallback

One-line pitch: project agents buy verified fixes, specialist agents earn bounties, and market outcomes become data for better orchestrators.

Sponsor use: Stripe/GitHub/Hermes/NVIDIA paths are represented with explicit real, recorded-real, fallback, and blocked labels. No fully-live overclaim.
```

## Expanded Version

```text
Agent Bounty Market

Tweet/video: [FINAL_TWEET_URL]
Repository: [REPO_URL]
Release tag: hackathon-mixed-rc10
Truth label: Mixed real/fallback

Agent Bounty Market turns software maintenance into a bounded transaction:
fund -> claim -> verify exact commit -> settle once. The demo shows a $25
bounty where the solver wallet keeps $20 as operating credit and sends $5
through the Stripe settlement path to the operator account. It also shows how
claims, declines, verifier results, payouts, and retained-credit spends become
trajectory data for future orchestrators.

Sponsor summary:
- Stripe: reviewed funding/webhook/Connect settlement path plus prior recorded-real sandbox evidence; fresh split transfer remains blocked without sandbox env.
- GitHub: digest-bound contract, claim, PR, and result schemas with fake transport in the bundle.
- Hermes: local executable evidence and schema-checked project/solver decision boundaries; model-backed decisions remain blocked without reviewed wrappers.
- NVIDIA/OpenShell: intended execution boundary with policy/manifest digests; current host uses fallback verifier because OpenShell/NemoClaw runtime is unavailable.

No secrets, private prompts, raw webhook payloads, or fully-live claims are in the release package.
```
