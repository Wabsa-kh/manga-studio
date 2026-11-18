# Verified status — 2026-11-18

- Public source prepared from a clean snapshot; the original private history is retained separately.
- GitHub Linux CI passed, including real synthetic media rendering, 30 fps modern assembly, persistence/failure tests and source-reference guards. See the repository Actions tab for exact commits/results.
- GitHub's production workflow dry run passed installation and configuration checks. ffmpeg, rclone and the official Colab CLI installed successfully. The existing Gemini key is configured as a private repository secret. Drive and Colab authentication secrets are **not connected**, so `production_ready=false` and no cloud production/GPU request was made.
- Real WeebCentral smoke test: one chapter, 19/19 validated pages, ~38.7 seconds. The site returned the 117-chapter list. Original source files and download receipts remain outside git.
- Live large-speech test: 2,200 cached narration words → 649.12 seconds of audio in 125.3 seconds, 18,905 reported total tokens. No billing dashboard audit was performed. This is a capacity sample, not a sustained daily qualification.
- New Isekai visual preview: 362.33 seconds, 720p30, 34 page shots, 102 sampled frames; no blank sampled frames. Render time ~271.5 seconds locally. Narration/story text was reused unchanged. Subject geometry covers all 34 displayed pages; phrase focus covers 32 spoken beats, with source-linked fallback framing for the remaining two.
- The original long local trial remains saved at 64 extracted pages and one 36-page scripted/rendered unit out of 1,897 pages. It was not silently marked complete or restarted through the old camera engine.

Not yet verified: authenticated Drive checkpoint/restore on the actual account, Colab user authentication and GPU upscaling, a complete hour-long cloud run, factual/style quality across the full book, long-term free Actions/Colab capacity, storage retention/garbage collection and YouTube upload/OAuth. These must be resolved before claiming unattended daily publishing.

Deployment update: 51 local tests pass, including resumable YouTube upload failures and duplicate prevention. Actual Google authorizations and a real upload remain unverified.
