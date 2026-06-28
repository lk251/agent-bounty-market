# Operator Finalization

This workflow keeps personal/operator data out of Git. The committed files stay
as templates; final tweet, Discord, Typeform, portal, and media reports are
rendered under ignored `.demo/` state.

## 1. Create Local State

```bash
cp -n submission/operator-submission.example.json .demo/operator-submission.json
$EDITOR .demo/operator-submission.json
```

Fill `repo_url`, `video_file_path`, `video_filename`, `team_name`,
`team_member_names`, `contact_email_or_handle`, and `bundle_backup_path`.
Leave `final_tweet_url`, `discord_confirmation_path`, and
`typeform_confirmation_path` empty until after posting/submitting.

## 2. Record And Check Video

Start the director:

```bash
nix develop --command python3 -m agent_bounty demo-director \
  --bundle demo/bundles/winning-run \
  --host 127.0.0.1 \
  --port 8788 \
  --duration 120
```

Record:

```text
http://127.0.0.1:8788/director-record.html?duration=120&autoplay=1
```

Check the final MP4:

```bash
nix develop --command python3 -m agent_bounty video-check \
  --file /absolute/path/to/final-video.mp4
```

If `ffprobe` is unavailable, create a local manually attested JSON report with
schema `agent-bounty-manual-media-report-v1`, add its path to
`manual_media_report_path`, and rerun the check with `--manual-report`.

## 3. Pre-Post Gate

```bash
nix develop --command python3 -m agent_bounty submission-finalize \
  --state .demo/operator-submission.json \
  --output .demo/final-submission \
  --check

nix develop --command python3 -m agent_bounty submission-check \
  --entry \
  --prepost
```

This validates the local state, video report, conservative X/Twitter character
counts, required `@NousResearch` tag, and `Mixed real/fallback` truth language.

## 4. Post And Submit

1. Use `.demo/final-submission/FINAL_TWEET.md` for the tweet/video post.
2. Post in X/Twitter with the final MP4 attached.
3. Save the resulting status URL in `final_tweet_url`.
4. Post the Discord submission using `.demo/final-submission/FINAL_DISCORD.md`.
5. Save a local confirmation note/screenshot path in `discord_confirmation_path`.
6. Submit Typeform using `.demo/final-submission/FINAL_TYPEFORM.md`.
7. Save a local confirmation note/screenshot path in `typeform_confirmation_path`.

## 5. Final Gate

```bash
nix develop --command python3 -m agent_bounty submission-finalize \
  --state .demo/operator-submission.json \
  --output .demo/final-submission

nix develop --command python3 -m agent_bounty submission-check \
  --entry \
  --final \
  --state .demo/operator-submission.json
```

Retain `.demo/final-submission`, the final MP4, the bundle backup, and local
confirmation evidence. Do not commit these local files.
