# Submission Portal Checklist

Status: draft until all `[FINAL_*]`, `[REPO_URL]`, and team placeholders are
filled.

## Release Identity

- Release tag: `hackathon-mixed-rc7`
- Truth label: `Mixed real/fallback`
- Bundle digest:
  `sha256:88beb2a882505aa33a84b39499c3e485ffdf47db389ed97dae0fcc6e41ee8219`
- Attestation digest:
  `sha256:8fba534b8761d5988dac86994d43a6b54d99927c40ad977f730c612e8ec3a182`
- Truth matrix digest:
  `sha256:4c2f88387d193813d90319f669b32b2e1269072c50eb265550ae545b7a5ef029`

## Before Recording

- Run `nix develop --command python3 -m agent_bounty submission-check --entry`.
- Run `nix develop --command python3 -m agent_bounty release-audit`.
- Start dashboard with the recording command in `submission/RELEASE_MANIFEST.json`.
- Hide unrelated terminal windows and private material.
- Prepare the concise tweet and Discord message.

## Before Tweeting

- Export `[FINAL_VIDEO_FILENAME]` as MP4/H.264.
- Confirm duration is within 1-3 minutes and ideally 1:45-2:15.
- Confirm `@NousResearch` appears in the tweet.
- Confirm `Mixed real/fallback` appears in the tweet or visible video context.
- Confirm optional sponsor tags are truthful in context.
- Confirm no final text makes an all-live claim.

## After Tweeting

- Save final tweet URL: `[FINAL_TWEET_URL]`.
- Open tweet in a logged-out/private browser if possible.
- Confirm video playback, title/description, and `@NousResearch` tag.
- Copy tweet URL into the Nous Discord submissions channel.
- Save Discord completion note/screenshot path: `[DISCORD_CONFIRMATION_PATH]`.

## Typeform

- Open `https://form.typeform.com/to/hpEifIK4`.
- Paste repository URL: `[REPO_URL]`.
- Paste final tweet/video URL: `[FINAL_TWEET_URL]`.
- Use `submission/TYPEFORM_FINAL.md` for field answers.
- Preserve `Mixed real/fallback` truth boundary in every free-text answer.
- Save Typeform confirmation note/screenshot path:
  `[TYPEFORM_CONFIRMATION_PATH]`.

## Backup Paths

- Final video file: `[FINAL_VIDEO_FILE_PATH]`.
- Local repository path: `[LOCAL_REPO_PATH]`.
- Final release bundle backup path: `[BUNDLE_BACKUP_PATH]`.

## Final Gate

Run this after all placeholders are filled:

```bash
nix develop --command python3 -m agent_bounty submission-check --entry --final
```

Expected before final posting: draft mode passes, final mode fails only because
operator placeholders remain.
