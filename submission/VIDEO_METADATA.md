# Video Metadata

Status: draft until `[FINAL_VIDEO_FILENAME]` and `[FINAL_TWEET_URL]` are filled.

## Duration

- Hard requirement: 1-3 minutes.
- Target duration: 1:45-2:15.
- Director target: 2:00 using `demo-director --duration 120`.
- Cut anything that pushes the video beyond 2:45 unless it is essential.

## Capture Source

- Preferred command:
  `nix develop --command python3 -m agent_bounty demo-director --bundle demo/bundles/winning-run --host 127.0.0.1 --port 8788 --duration 120`
- Preferred capture URL:
  `http://127.0.0.1:8788/director-record.html?duration=120&autoplay=1`
- Presenter notes URL, kept off capture:
  `http://127.0.0.1:8788/director-notes.html`
- Fallback dashboard URL:
  `http://127.0.0.1:8787/dashboard.html`

## Export

- Filename: `[FINAL_VIDEO_FILENAME]`, recommended pattern
  `agent-bounty-market-hackathon-YYYYMMDD.mp4`.
- Container: MP4.
- Codec: H.264/h264 video with AAC audio for common X/Twitter compatibility.
- Resolution: 1920x1080 preferred; 1280x720 acceptable if terminal text remains
  legible.
- Frame rate: 30 fps preferred; 60 fps acceptable if file size and upload are
  stable.

## Visual Checks

- `Mixed real/fallback` mode badge visible.
- Director scenes present: Problem, Project spends, Agents choose,
  Verification, Settlement, Flywheel, Close.
- No terminal window exposes secrets, raw webhook payloads, private prompts,
  personal files, browser sessions, or unrelated home-directory content.
- Repository URL and release tag are readable.
- Dashboard truth matrix is legible.
- Demo does not claim that every sponsor path ran live.

## Audio Checks

- Voice or captions explain the problem, the lifecycle, the protected verifier,
  and the truth boundary.
- Audio is not clipped.
- Background noise is low enough for judges to understand the pitch.

## Upload Checks

- Attach video to the first tweet/post.
- Confirm the uploaded video plays in the composer before posting.
- After posting, open `[FINAL_TWEET_URL]` in a logged-out/private browser where
  possible.
- Confirm the video plays and the required `@NousResearch` tag is visible.
