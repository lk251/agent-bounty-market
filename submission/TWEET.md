# Tweet Package

Status: draft until `[REPO_URL]`, `[DEMO_URL_OPTIONAL]`, and final video upload
state are filled by the operator.

Counting rule: raw Unicode code point count, including placeholders. X/Twitter
may count real URLs differently, so recheck in the composer before posting.
Attach the 1-3 minute demo video to the first post.

## Variant A: Single-post concise

### Single Post Concise
Status: draft
Character count: 275
```tweet
Agent Bounty Market for the @NousResearch hackathon: fund a bounded software task, let agents claim work, verify the exact commit, and settle once. Truthful Mixed real/fallback demo with Stripe, GitHub, Hermes, and NVIDIA/OpenShell paths visible. @NVIDIAAI @stripe [REPO_URL]
```

## Variant B: Two-post thread

### Thread 1 Video Post
Status: draft
Character count: 243
```tweet
For the @NousResearch hackathon, Agent Bounty Market shows software work becoming a bounded transaction: fund -> claim -> verify exact commit -> settle once. Demo video attached. Mixed real/fallback is visible in the release bundle. [REPO_URL]
```

### Thread 2 Trust Boundary
Status: draft
Character count: 262
```tweet
@NousResearch The kernel is the point: candidate-owned code cannot authorize payment; a protected verifier and digest-bound receipts do. Stripe/GitHub/Hermes/NVIDIA paths are separated as real, recorded-real, fallback, or blocked. Mixed real/fallback. [REPO_URL]
```

## Variant C: Ultra-short fallback

### Ultra-short Fallback
Status: draft
Character count: 117
```tweet
@NousResearch Agent Bounty Market: funded -> verified exact commit -> paid once. Mixed real/fallback demo. [REPO_URL]
```

## Posting Notes

- Required tag: `@NousResearch`.
- Optional tags used where accurate and within budget: `@NVIDIAAI`, `@stripe`.
- Truth label to preserve: `Mixed real/fallback`.
- Do not add all-live claims; those are false for this release candidate.
- Replace `[REPO_URL]` with the final GitHub repository or release URL only if
  the URL is useful in the post.
- Replace `[DEMO_URL_OPTIONAL]` only if an external demo page exists; the normal
  submission path is attached video plus tweet URL.
