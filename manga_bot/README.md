# Unattended manga worker

This is the earlier low-level worker reference. For GitHub deployment, Drive persistence and the current entry point, use the repository's [main README](../README.md) and [setup guide](../docs/SETUP.md). The commands below are useful for isolated local jobs, not the complete library/Colab orchestration.

This is a book-independent continuation of the tested v9 pipeline. It reads original image bytes, uses Flash Lite for extraction, gives Hydrogen all original unit pages for final narration, carries evidence-linked character/continuity memory, generates Gemini Charon speech, aligns speech locally and renders immersed source-linked camera moves. No paid fallback or key cycling is configured.

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m manga_bot.worker --config './job/config.json'
```

The existing config selects the user's 45–60-minute parts. The bot chooses real unit/chapter boundaries using measured audio lengths and model stopping-point scores. The final remainder can be shorter. An unusually long indivisible unit can be an explicit length exception. It never adds filler or invents a resolved cliffhanger to fit a duration.

Each unit can be watched as an intermediate evaluation preview in `units/unit-NNNN/chapter.mp4`. Final parts appear in `parts/part-NNN/video.mp4`, with `editable.mlt`, timeline markers and media credits. The editable project references the camera clips and separate narration tracks; preserve the job directory. Unit contact sheets show entry, middle and exit frames from every page shot.

`status.json` and `REPORT.md` show actual progress, usage and holds. `events.jsonl` distinguishes technical code changes from content interventions. Drafts and original receipts remain on disk. The new-book test has no manual factual corrections or narration rewrites. This is an evaluation pipeline: automatic technical checks and source-linked generation do not certify factual perfection or authorize publication.

Daily quotas are per project/model, not per key. The worker honors observed reset times and keeps its own conservative allowance in a shared SQLite budget. Existing workstation quota observations are also respected. Uncertain accepted requests keep their reservation and have a bounded, delayed recovery; repeated failures stop with a reason. Access or content screening rejections require attention, rather than routing around the rejection. Create a file named `STOP` in the job folder to stop gracefully. Remove it and rerun the same command to resume.

The source and output paths are frozen in `inventory.json`; do not replace page files mid-run. Keep the source directory and at least 4 GB of free output space. Never delete original images to make room. The worker is not a Windows service: it needs a running computer, network access and the process alive. Restart it after a reboot, or use the container restart policy below. It does not deploy itself to a server.

## Cloud container

Build from this repository root (the Dockerfile copies only Python modules and the two style resources, never credentials or generated outputs):

```bash
docker build -f manga_bot/Dockerfile -t manga-bot .
docker run -d --name manga-bot --restart unless-stopped \
  --env GEMINI_API_KEY \
  -v /your/manga:/source:ro -v /your/job:/job \
  manga-bot
```

Set `GEMINI_API_KEY` securely in the host environment. Create `/your/job/config.json` with title, source `/source`, output `/job`, provider_state `/job/provider-state`, unit_pages 40, prefetch_units 2 and minimum_free_gb 4. A fresh job uses Linux paths; a Windows job needs an explicit path migration before resuming in Linux. Persist the job volume across restarts. Use one shared provider-state location for jobs using the same Google project. CPU rendering and local Whisper require sufficient server RAM, storage and runtime; free model APIs do not make a paid cloud server free. The container definition is supplied; actual cloud deployment has not been performed.

Regression checks: `python -m unittest test_manga_bot -v`.
