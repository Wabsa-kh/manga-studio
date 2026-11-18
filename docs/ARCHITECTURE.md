# Modules and state

- `manage`: manga library, bounded runs, per-title states and diagnostic report.
- `catalog`: owner-editable manga list, priorities, pause/resume and per-book part durations.
- `ingest`: URL validation, pinned downloader, complete-chapter receipts.
- `upscale` / `colab_bridge`: pinned ESRGAN models, verified 4× dimensions, per-page Drive checkpoint and Colab lifecycle.
- `providers` / `routing` / `credentials` / `core.Budget`: native Google plus fixed-host NIM and free-only OpenRouter adapters, persistent credential selection, shared/project-scoped usage, observed scope merging, key quarantine, typed cooldowns and writer fallbacks. Unknown acceptance and content rejection remain held across route changes. Short pacing waits continue inside a bounded worker run.
- `stages`: original-image evidence, source IDs, stronger writer, character memory and unresolved story handoffs.
- `worker` / `part_audio`: source-order production, part decisions, frozen scope, speech packing across units and measured splitting.
- `visual_layout` / `focus_timing`: separate subject geometry and exact narration-phrase timing. They do not rewrite story prose.
- `camera_v11` / `render_v11`: configurable deterministic poses, fractional-pixel transforms, subtle perspective, brief transfers, holds, blur and wipes/fades.
- `visual_review`: every-page contact sheets, render/source frame comparisons and editable Shotcut timeline.
- `storage`: immutable content-addressed objects, versioned manifests and publish-last pointer; SQLite snapshot, path rebasing and lazy media hydration. The CPU worker fetches only the upscaled pages needed for its current unit. Finished parts and intermediate media remain referenced remotely after acknowledged local eviction.
- `publishing`: title/description queue, channel-bound resumable YouTube uploads and durable private receipts.

Generated outputs and credentials never belong in git. Model secrets live in environment variables/GitHub Secrets. Checkpoints intentionally exclude auth directories, model weights, temporary and unfinished files. The code snapshot retains a set of older helper modules through the tested dependency closure; they are implementation dependencies, not alternate production entry points. Use `manga_bot.manage` for deployment, rather than launching historical benchmark scripts.

Content or identity uncertainty is review metadata. Schema/reference checks are not proof that the story is factually perfect. Content screening failures require review; the system does not change prompts/images or switch providers to evade screening. Source text is treated as untrusted story material, never as commands.

The original Spladenly notebook uses an interactive Drive mount. The headless adapter uses the same pinned ESRGAN implementation/models, with rclone for authenticated handoff and validation after each page. Whole-book initial downloads and upscaling can require multiple bounded runs before the first finished video. Incremental per-part upscaling, explicit storage retention and full-book provider qualification remain useful next improvements. Route profiles and their measured limits are documented in provider-profiles.json and PROVIDER_VERIFICATION.md.
