# Live Setup Runbook

This runbook uses placeholders only. Do not commit real API keys, webhook
secrets, checkout URLs, or raw webhook payloads.

## Environment Placeholders

```bash
export NVIDIA_API_KEY=...
export AGENT_BOUNTY_NVIDIA_MODEL_ID=...
export AGENT_BOUNTY_RUN_HERMES_PROJECT_AGENT=1
export AGENT_BOUNTY_HERMES_PROJECT_EVALUATE_COMMAND='...reviewed project wrapper...'
export AGENT_BOUNTY_HERMES_SOLVER_EVALUATE_COMMAND='...reviewed solver wrapper...'
export AGENT_BOUNTY_HERMES_CONTEXT_TOKENS=65536
export AGENT_BOUNTY_GITHUB_INTEGRATION=1
export AGENT_BOUNTY_GITHUB_TOKEN=...
export GH_TOKEN=...
export AGENT_BOUNTY_GITHUB_REPOSITORY=owner/repo
export AGENT_BOUNTY_GITHUB_WEBHOOK_SECRET=...
export AGENT_BOUNTY_STRIPE_SANDBOX=1
export STRIPE_TEST_SECRET_KEY=sk_test_...
export STRIPE_TEST_WEBHOOK_SECRET=whsec_...
export STRIPE_TEST_CONNECTED_ACCOUNT_ID=acct_...
export STRIPE_TEST_PLATFORM_ACCOUNT_ID=acct_...
export AGENT_BOUNTY_PUBLIC_BASE_URL=http://127.0.0.1:4242
```

## Checklist

### Hermes/NVIDIA

- [ ] NVIDIA_API_KEY configured is not ready
- [ ] NVIDIA model ID configured is not ready
- [ ] Hermes context >= 64000 is not ready
- [ ] Project wrapper configured is not ready
- [ ] Solver wrapper configured is not ready
- [ ] set AGENT_BOUNTY_RUN_HERMES_PROJECT_AGENT=1
- [ ] set AGENT_BOUNTY_HERMES_PROJECT_EVALUATE_COMMAND to a reviewed project wrapper
- [ ] set AGENT_BOUNTY_HERMES_SOLVER_EVALUATE_COMMAND to a reviewed solver wrapper
- [ ] set NVIDIA_API_KEY for real NVIDIA NIM/Nemotron
- [ ] set AGENT_BOUNTY_NVIDIA_MODEL_ID after model discovery
- [ ] set AGENT_BOUNTY_HERMES_CONTEXT_TOKENS >= 64000

Commands:

```bash
python -m agent_bounty hermes-install-skills
python -m agent_bounty hermes-status --discover-models
python -m agent_bounty demo-hermes-decisions --db .demo/hermes-live.sqlite3 --require-real
```

### OpenShell/NemoClaw

- [ ] Docker available is not ready
- [ ] OpenShell available is not ready
- [ ] NemoClaw/community artifacts is not ready
- [ ] docker executable not found on PATH
- [ ] openshell executable not found on PATH
- [ ] set NVIDIA_API_KEY for real NVIDIA NIM/Nemotron inference
- [ ] set AGENT_BOUNTY_NVIDIA_MODEL_ID after NVIDIA model discovery

Commands:

```bash
python -m agent_bounty nvidia-runtime-status
python -m agent_bounty nvidia-runtime-status --discover-models
python -m agent_bounty demo-nvidia-sandbox --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency --require-real
```

### GitHub

- [ ] gh CLI available/auth status is not ready
- [ ] GitHub integration enabled is not ready
- [ ] Repository configured/retrievable is not ready
- [ ] Webhook secret configured is not ready
- [ ] set AGENT_BOUNTY_GITHUB_INTEGRATION=1
- [ ] set AGENT_BOUNTY_GITHUB_TOKEN or GH_TOKEN to a fine-grained development token
- [ ] set AGENT_BOUNTY_GITHUB_REPOSITORY=owner/repo
- [ ] set AGENT_BOUNTY_GITHUB_WEBHOOK_SECRET for signed webhook ingestion

Commands:

```bash
python -m agent_bounty github-status
python -m agent_bounty github-webhook-serve --db .demo/github-live.sqlite3 --host 127.0.0.1 --port 4343
python -m agent_bounty demo-github-motoko-live --db .demo/github-live.sqlite3 --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
```

### Stripe

- [ ] Sandbox flag enabled is not ready
- [ ] Test secret key configured is not ready
- [ ] Webhook secret configured is not ready
- [ ] Connected account configured is not ready
- [ ] Platform/connected account safe retrieval is not ready
- [ ] set AGENT_BOUNTY_STRIPE_SANDBOX=1
- [ ] set STRIPE_TEST_SECRET_KEY
- [ ] set STRIPE_TEST_WEBHOOK_SECRET from stripe listen
- [ ] set STRIPE_TEST_CONNECTED_ACCOUNT_ID to a test connected account

Commands:

```bash
stripe listen --events payment_intent.succeeded,payment_intent.payment_failed,checkout.session.completed,checkout.session.expired,transfer.created,transfer.reversed --forward-to http://127.0.0.1:4242/stripe/webhook
python -m agent_bounty stripe-webhook-serve --db .demo/stripe.sqlite3 --host 127.0.0.1 --port 4242
python -m agent_bounty stripe-status
python -m agent_bounty stripe-create-checkout --db .demo/stripe.sqlite3 --project-id project_motoko --source owner --amount-cents 2500 --currency usd --success-url http://127.0.0.1:4242/success --cancel-url http://127.0.0.1:4242/cancel
python -m agent_bounty stripe-process-events --db .demo/stripe.sqlite3
python -m agent_bounty demo-economic-loop-live --db .demo/stripe.sqlite3 --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
python -m agent_bounty stripe-reconcile --db .demo/stripe.sqlite3 --remote
```

## Verify

```bash
python -m agent_bounty live-setup-wizard --format json
python -m agent_bounty demo-preflight --mode live
```
