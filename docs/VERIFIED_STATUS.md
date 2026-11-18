# Verified status — 2026-11-18

## Production qualification update — November 19 Pakistan time

- Four WeebCentral titles are now queued for 45–60-minute private parts; see [selection notes](MANGA_SELECTION.md).
- Real GitHub downloads encountered source HTTP 403. The owner requested Colab downloads. Downloads now use a separate Colab CPU session, followed by a GPU session for upscaling.
- A real Colab CPU runtime allocated and the pinned downloader found 42 chapter entries for 7th Time Loop. Chapter 1's 45 original pages were downloaded, hash-verified and checkpointed to Drive. They were restored to a fresh Windows directory with the completion receipt intact. This qualifies one chapter, not the entire book or the GPU stage.
- Drive hit request-rate exhaustion through rclone's shared OAuth app. Drive API access was enabled on the owner's existing OAuth app, fresh consent was completed against the existing archive, and the GitHub storage secret was updated. No archive was replaced.
- Batched Drive upload/restore passed a real isolated round-trip (52.3 seconds), and the 51-file production checkpoint restored with integrity checks in 92.5 seconds. These are small samples, not a general sustained transfer benchmark. The temporary round-trip folder was removed after verification.
- Checkpoints now batch new immutable blobs and retain publish-last manifests. GPU progress normally checkpoints every 16 verified pages or 60 seconds and flushes at completion, reducing per-page transfer overhead. Sudden VM loss can require repeating the latest uncheckpointed upscale batch.
- The initial Colab download run was deliberately stopped after preserving the first chapter to deploy transfer batching. The [continuation run](https://github.com/Wabsa-kh/manga-studio/actions/runs/44387332650) resumes those saved pages. A produced hour-long video and a real private YouTube upload are still outstanding.

## Earlier verification

- Public source prepared from a clean snapshot; the original private history is retained separately.
- GitHub Linux CI passed, including real synthetic media rendering, 30 fps modern assembly, persistence/failure tests and source-reference guards. See the repository Actions tab for exact commits/results.
- Required authentication and the model-pool JSON are configured in six GitHub Secrets. Drive write/read validation passed; Colab OAuth runtime-list access returned HTTP 200; YouTube OAuth channel access and eligibility for uploads longer than 15 minutes were verified. The owner changed the OAuth app to In production, and fresh YouTube authorization was installed afterward. Upload privacy remains private.
- The real cloud worker run without a manga URL passed and saved a Drive checkpoint, reporting `production_ready=true`, `publishing_ready=true` and `run_finished`. It performed no story, speech, GPU allocation or video upload. See [cloud connection run](https://github.com/Wabsa-kh/manga-studio/actions/runs/44362832949).
- That Linux checkpoint was restored to a fresh Windows directory with hash verification, including the dashboard and SQLite usage database. Existing manga/video work was not regenerated for this connection test.
- GitHub Linux CI passed all 87 tests on Ubuntu 24.04, including pooled generation/speech, unknown-outcome holds, source guards, rendering, quota scopes, model fallback, short pacing waits and long-manga part coverage. Media dependencies download concurrently and apt verifies their hashes against its signed package index. Installation has a 15-minute limit. See [CI result](https://github.com/Wabsa-kh/manga-studio/actions/runs/44377514940).
- The cloud worker loaded all twelve model credentials and reported NIM, OpenRouter, production and publishing connections ready in an empty-library run: [model-pool cloud check](https://github.com/Wabsa-kh/manga-studio/actions/runs/44374433057). This checks setup and checkpointing, not full video production.
- Live rotation completed four small requests using four Google credentials. NIM and free OpenRouter writers passed the production script checks using four cached evidence pages. NIM reading was kept out of the default source-authority role after visual inspection found attribution/action mistakes. See [provider verification](PROVIDER_VERIFICATION.md).
- Real WeebCentral smoke test: one chapter, 19/19 validated pages, ~38.7 seconds. The site returned the 117-chapter list. Original source files and download receipts remain outside git.
- Live large-speech test: 2,200 cached narration words → 649.12 seconds of audio in 125.3 seconds, 18,905 reported total tokens. No billing dashboard audit was performed. This is a capacity sample, not a sustained daily qualification.
- New Isekai visual preview: 362.33 seconds, 720p30, 34 page shots, 102 sampled frames; no blank sampled frames. Render time ~271.5 seconds locally. Narration/story text was reused unchanged. Subject geometry covers all 34 displayed pages; phrase focus covers 32 spoken beats, with source-linked fallback framing for the remaining two.
- The original long local trial remains saved at 64 extracted pages and one 36-page scripted/rendered unit out of 1,897 pages. It was not silently marked complete or restarted through the old camera engine.

Not yet verified: Colab GPU allocation and upscaling, a complete hour-long cloud run, factual/style quality across the full book, sustained free Actions/Colab capacity, storage retention/garbage collection and an actual YouTube video upload. These must be resolved before claiming unattended daily publishing.

Resumable YouTube upload failures and duplicate prevention are covered by automated tests. No real upload has yet been performed.
