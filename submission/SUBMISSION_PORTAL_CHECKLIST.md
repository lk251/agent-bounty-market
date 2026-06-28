# Submission Portal Checklist

Status: draft until all `[FINAL_*]`, `[REPO_URL]`, and team placeholders are
filled.

## Release Identity

- Release tag: `hackathon-mixed-rc10`
- Truth label: `Mixed real/fallback`
- Bundle digest:
  `sha256:1765bb2e57ed2e8c0d198591e6f52b77439f33266ca49fbaa02410f836dbedf4`
- Attestation digest:
  `sha256:5c4703fc9c929198df97eae12a5d5c83310d736dd76edce64308f8a9eaba04d1`
- Truth matrix digest:
  `sha256:a704f3e1a90d141c0f9c92bef2c4656cef92b5abf93bdeb1abfd9ed342530bc1`

## Before Recording

- Run `nix develop --command python3 -m agent_bounty submission-check --entry`.
- Run `nix develop --command python3 -m agent_bounty release-audit`.
- Copy `submission/operator-submission.example.json` to
  `.demo/operator-submission.json` and fill repo/team/video fields.
- Start dashboard with the recording command in `submission/RELEASE_MANIFEST.json`.
- Hide unrelated terminal windows and private material.
- Prepare the concise tweet and Discord message.

## Before Tweeting

- Export `[FINAL_VIDEO_FILENAME]` as MP4/H.264.
- Run `nix develop --command python3 -m agent_bounty video-check --file
  [FINAL_VIDEO_FILE_PATH]`.
- Run `nix develop --command python3 -m agent_bounty submission-finalize
  --state .demo/operator-submission.json --output .demo/final-submission
  --check`.
- Run `nix develop --command python3 -m agent_bounty submission-check --entry
  --prepost --state .demo/operator-submission.json`.
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
nix develop --command python3 -m agent_bounty submission-finalize --state .demo/operator-submission.json --output .demo/final-submission
nix develop --command python3 -m agent_bounty submission-check --entry --final --state .demo/operator-submission.json
```

Expected before final posting: draft mode passes, final mode fails only because
operator placeholders remain.
