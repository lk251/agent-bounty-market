# Winning Run Bundle Slot

The authenticated recorded-real bundle should be captured here only after a
real full demo run is available and sanitized.

For current deterministic rehearsals, use:

```bash
python -m agent_bounty demo-rehearse --mode local \
  --bundle .demo/bundles/local-rehearsal \
  --motoko-repo /home/mares/repos/motoko-issue-1-tui-input-latency
```

Then replay it with:

```bash
python -m agent_bounty demo-replay --bundle .demo/bundles/local-rehearsal
```
