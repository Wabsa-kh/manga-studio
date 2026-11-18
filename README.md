# Manga Studio

A public-source, resumable manga production worker with private credentials and media storage. Give it a WeebCentral series link, keep the manga library and generated assets on Google Drive, and continue bounded work in GitHub Actions. The current visual engine produces 30 fps character/action-focused page cameras with fractional-pixel movement, short transfers, longer holds, sampled paper backgrounds, subtle perspective and feathered wipes/fades.

**Current status:** software and failure tests are implemented; GitHub CI verifies Linux execution. Google Drive and Colab user credentials must be connected before live cloud production. A complete link → downloader → Colab GPU → story → hour-long video run has not yet been qualified. Private-first resumable YouTube uploading is implemented; owner OAuth authorization and a live upload still need verification. Daily output is a target, not a guaranteed free entitlement.

## Start here

1. Read [SETUP.md](docs/SETUP.md) and connect Drive and Colab once through GitHub secrets. Existing Gemini credentials can be stored privately as a repository secret.
2. Open **Actions → Daily manga worker → Run workflow**. Paste a full `https://weebcentral.com/series/...` link. The default dry run checks connections without model/GPU requests. Turn dry run off for production after setup.
3. Leave the link blank to continue the saved library. A daily run is scheduled at 08:17 UTC. Successful and waiting jobs publish a readable summary. Finished media and recoverable state belong on Drive; small diagnostic reports are GitHub artifacts.

Configure [config/settings.json](config/settings.json) for part duration, narration pace, model IDs, conservative request ceilings, reading concurrency, speech batching, GPU selection and camera settings. The selected default is **45–60-minute parts**. A shorter final remainder is allowed. Current AI routes use one Google project/key; there is no paid router fallback or quota-evasion key rotation.

## Pipeline

`series link → verified downloads → 4× Colab upscale → original-image evidence → continuity-aware script → frozen parts → packed speech → measured timing → subject layout + phrase focus → deterministic camera render → verification + upload queue`

Original files remain intact. Evidence models receive full original scan bytes, without client resizing. Final rendering can use the verified 4× assets with the same normalized geometry. This avoids sending huge upscaled files to the writer unnecessarily. Reader geometry and wording are fallible; the stronger writer receives the actual original images as authority. Saved scripts, character memory and source references are reused on restart.

## What survives failures

- Downloads are complete only when expected image count, sequential numbering and decoding pass. Each chapter has a receipt.
- Immutable SHA256 blobs and a publish-last manifest keep the previous complete checkpoint readable if an upload stops. SQLite uses a consistent backup; Windows/Linux path relocation is handled on restore.
- Model request reservations and an `unknown outcome` receipt are persisted **before dispatch**. If durable storage fails, the model call is not sent. Unknown accepted calls cool down and remain counted; exactly-once execution cannot be guaranteed by providers without idempotency support.
- Daily quota holds save a resume time and end bounded work. Repeated 503s enter an hourly cooldown, rather than permanently stopping the library. Authentication, invalid sources and content rejection are flagged for review. Rejected story content is neither silently omitted nor routed around provider screening.
- Completed script/audio/video assets are reused. An interrupted current render can require rerendering that bounded unit; completed units/parts are retained. There is no claim that every possible failure can be repaired without owner input.
- The library manager continues other eligible manga when one is waiting or needs review. Secret files, private auth, model weights and unfinished files are excluded from checkpoints.

## Local commands

```bash
python -m pip install -r manga_bot/requirements.txt
python -m manga_bot.manage doctor
python -m manga_bot.manage add https://weebcentral.com/series/SERIES_ID --title "Manga title"
python -m manga_bot.manage list
python -m manga_bot.manage run
python -m manga_bot.manage report
python -m unittest test_manga_bot test_visual_v11 test_studio -v
```

For local testing, set the storage backend to `local` and disable upscaling when no GPU is attached. This explicit configuration uses original pages for rendering. Use a separate state folder for experiments. Never commit a state folder, credentials, manga pages or generated videos.

## Tools and limits

See [ARCHITECTURE.md](docs/ARCHITECTURE.md), [CAPACITY.md](docs/CAPACITY.md) and [TESTING.md](docs/TESTING.md). The source downloader is pinned to [Yui007/weebcentral_downloader](https://github.com/Yui007/weebcentral_downloader). The GPU adapter uses the models and ESRGAN implementation referenced by [Spladenly's notebook](https://github.com/Spladenly/ai-manga-upscale-colab). Their code/models retain their upstream licenses; third-party source is fetched at pinned revisions rather than copied into this repository. Colab is controlled using the [official Google CLI](https://github.com/googlecolab/google-colab-cli).

The [video analysis prompt](docs/VIDEO_ANALYSIS_PROMPT.md) asks a video model for timestamped framing/motion measurements and uncertainty, to refine presets without inventing exact reference settings.

The [reference study](docs/REFERENCE_STUDY.md) preserves the language/visual analysis behind this project. The active writing rules remain [narration_style.txt](narration_style.txt) and its reference calibration, loaded directly by the writer.
