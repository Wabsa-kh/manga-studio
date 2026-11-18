# Manage the manga queue

Edit `config/manga.json` on GitHub with the pencil button and commit your changes. It starts with an empty manga array. Replace the example links below with actual WeebCentral series links:

```json
{
  "manga": [
    {
      "title": "First manga",
      "url": "PASTE_FIRST_WEEBCENTRAL_SERIES_LINK",
      "enabled": true,
      "priority": 1,
      "part_minutes": [45, 60]
    },
    {
      "title": "Second manga",
      "url": "PASTE_SECOND_WEEBCENTRAL_SERIES_LINK",
      "enabled": true,
      "priority": 2,
      "part_minutes": [30, 45]
    }
  ]
}
```

This is a public repository, so entries in this file are public. Media, checkpoints, credentials and detailed production reports remain in private storage.

Lower priority numbers run first; ties follow file order. A book can use the available worker time before the next book starts. This is a priority queue, not a round-robin scheduler. A waiting book retains its place and saved progress. All books currently share the deployed Gemini provider budget.

Set `enabled` to false to pause both new production and uploads for that book. Removing an entry pauses a book that was managed by the list, preserving its files and receipts. Adding it back resumes saved work. It does not clear quota holds or review requirements. Changing length affects future, unfrozen parts; it does not rebuild completed videos or change an already frozen part.

You can also add one manga using Actions > Daily manga worker > Run workflow > manga_url. Such manually added jobs persist in the private library and are not removed by an empty list. The list is the easiest place to give a manga a readable title, priority and individual duration.

Saving the list runs CI checks. Production starts on the daily schedule at 08:17 UTC / 13:17 Pakistan, or when you run Daily manga worker manually with dry_run disabled. Leave manga_url blank when using the list. Dry run only checks connections; it does not import or process the list.

# Video length and chapter decisions

`part_minutes` is the target duration of each uploaded part. `[45,60]` requests roughly 45–60 minutes per video. If omitted for a manga, the global `part_minutes` in `config/settings.json` applies. Supported ranges are 1–240 minutes; short ranges may be impractical with large writing units.

Chapters are read in source order. The processing unit normally holds up to 40 original pages and 50 MiB. Chapter/subchapter groups stay together when possible; oversized chapters split into consecutive units. A unit is an internal reading/writing chunk, not necessarily a video.

The writer scores the actual end of each unit from 1 (continuing action) to 5 (good stopping point). The part planner accumulates adjacent units, estimates duration from their word counts and the configured speech pace, then chooses a suitable scored boundary within the requested range. It cannot select an arbitrary panel midway through a unit. It preserves the source's chapter order, flashbacks, unresolved scenes and cliffhangers instead of inventing an ending.

Current part-audio batching freezes membership before speech generation. Duration initially uses a word-count estimate at 207 words per minute; measured audio and small tempo adjustments determine the rendered duration. It is a target range, not an exact guaranteed runtime. A final remainder can be shorter; unusually large units can exceed the range. There is no fixed number of manga chapters per hour.

# Other settings

| Setting | Meaning |
|---|---|
| `max_run_minutes: 240` | Processing time per worker run, not video length |
| `daily_target_minutes: [60,120]` | Planning information; currently not an enforced daily output limit |
| `youtube.max_uploads_per_run: 1` | At most one successful upload per run; manual extra runs can upload more |
| `youtube.privacy: private` | Initial upload visibility |
| `words_per_minute: 207` | Narration pace and duration estimate |
| `unit_pages: 40` | Maximum pages in an internal writing unit |
| `reader_batch_pages: 2` | Pages supplied together to the reading stage |

# Complete workflow

Restore Drive state → import manga-list changes → choose the first enabled eligible book → download and verify original pages in a Colab CPU runtime → save them to Drive → upscale in a Colab GPU runtime → read original pages → write source-linked narration with prior story memory → freeze a video part → generate speech and timing → render focused page-camera video → assemble and verify the part → checkpoint it to Drive → upload privately to the configured YouTube channel.

`download.backend` is now `colab`. The pinned WeebCentral downloader runs inside Colab, not on GitHub. A CPU download session and a GPU upscale session are separate, so a blocked download does not reserve GPU time. Each verified chapter is checkpointed; interrupted downloads resume their receipts. GitHub restores Colab's newest checkpoint before continuing, including after a disconnect. Colab access to the source and GPU allocation still require live qualification. Set the backend to `worker` only to deliberately return downloads to the GitHub worker.

The downloader currently completes the requested book's chapter list before the upscale/reading stage. Upscaling currently completes before production starts. These stages are not a streaming chapter-by-chapter upload system yet.

Minute-level pacing and transient cooldowns of up to 120 seconds checkpoint and continue inside the current run. Longer waits save successful work and a retry time for a later scheduled run. This prevents a brief RPM pause from wasting an otherwise usable day. Finished videos can upload while AI generation is waiting. Invalid credentials, content rejections or ambiguous uploads may require review; no system can automatically guarantee completion for every rejection.

The private Drive checkpoint contains library.json, dashboard.json, REPORT.md, usage snapshots, request receipts, scripts, speech and completed media. The public Actions report shows connection booleans and generic run state.

# Keys and models

The production worker now rotates credentials through one encrypted GitHub secret, `MODEL_CREDENTIALS_JSON`. The local private file is `model-credentials.json` in the setup-private folder outside the repository. Existing keys have already been installed; you do not need to enter them again. A single `GEMINI_API_KEY` is still supported if no pool secret is supplied.

| Task | First route | Enabled fallback |
|---|---|---|
| Original-page reading and visual evidence | Google Gemini 3.5 Flash-Lite | Other usable Google credentials; waits if the reader service itself is unavailable |
| Final narration script | Google Gemini 4 Hydrogen | NVIDIA NIM Nemotron 3.5 Super VL, then its free OpenRouter route |
| Speech | Google Gemini 3.8 Flash TTS, Charon | Other usable Google credentials; voice stays consistent |
| 4x upscaling | ESRGAN on Colab T4 | Saved GPU task resumes later if unavailable |
| Camera animation, timing and assembly | Local CPU renderer and Whisper alignment | Reusable validated media checkpoints |

Google's writer receives the original images plus the extracted evidence. NIM and OpenRouter writer fallbacks receive that evidence and prior story memory without original images, reducing image processing and avoiding image-count constraints. They use the same source-citation, coverage and writing checks.

NIM original-page reading is available as a disabled experimental profile in `config/provider-profiles.json`. A real source inspection found speaker/action mistakes even though its output format passed validation. It is deliberately not the default source authority. A completed JSON response is not proof that its story facts are correct.

The active stage routes and fallback order are in `config/settings.json` under `providers`. The profile file supplies copyable route examples; changing a profile entry alone does not change the active routes. Writer fallbacks run on known service/quota failures or a structurally invalid completed response. Unknown accepted requests are not automatically replayed against another provider. Content-screening rejections stop that logical request for review.

## How key rotation works

The credential selected least recently is tried first. Selection history and quota reservations live in the checkpointed usage database, so restarting a GitHub worker does not reset the counters. The same successful request can be served from cache regardless of which key is currently selected.

Google project numbers are optional. This owner's Google credentials use separate-account labels based on the owner's statement. Those labels are provisional accounting scopes, not proof of multiplied entitlement. If Google's quota-error metadata identifies a shared project, the bot merges that project's attributed reservations without losing usage history. Explicit project mappings can also be supplied. Unmapped credentials without an independent-account declaration share one conservative budget.

OpenRouter keys share a global provider allowance; creating more accounts or keys does not establish more capacity. A 429 does not trigger attempts through all seven keys in the same free-model pool. A different explicitly free model may be configured as another route. Named OpenRouter models must have a `:free` suffix and zero prompt/completion pricing in the current catalog; paid routes are rejected before dispatch.

NIM credentials share one budget in this deployment. The shipped shared safety ceilings are 24 RPM / 500 requests per day for NIM and 20 RPM / 50 requests per day for OpenRouter, configurable under `quota_limits`. Each model route also has its own local ceilings. These are conservative client limits, not confirmed provider entitlements. API limit responses and retry times remain authoritative. Local daily accounting uses the project's Pacific-day clock; server-provided reset delays are additionally honored.

An HTTP 401 quarantines that credential and tries another usable key. Replacing its secret value clears that credential's quarantine without deleting quota history. HTTP 402/403 require access/billing review, with no payment or credential cycling. A known 503 can use the next configured writer provider. A timeout after possible acceptance is preserved as an unknown outcome instead of blindly sending the same work through every key. NIM asynchronous status polling remains tied to the original request ID.

Quota reservations are saved before dispatch. Private receipts record the actual provider, model, credential label, quota group, completion status, usage when returned, and elapsed time. They do not contain API key values. Raw generated text is retained; schema normalization only removes fields explicitly forbidden by the requested JSON schema, without rewriting permitted facts or filling missing values.

Google OAuth credentials for Drive, Colab and YouTube refresh through their saved offline credentials. That is separate from Gemini API-key rotation.

See [Google project-level limits](https://ai.google.dev/gemini-api/docs/rate-limits) and [OpenRouter's shared-limit rules](https://openrouter.ai/docs/api-reference/limits).

## Large manga and part continuity

A new part does not reset character identities, prior events or unresolved threads. Each writing unit receives previous handoffs, the character registry and recent narration. Source flashbacks and delayed reveals stay in source presentation order. The bot does not invent the events skipped between chapters.

For example, once the accumulated script reaches roughly 54 minutes and the current unit has a good stopping score, the planner can freeze Part 1 there. The next consecutive unit begins Part 2. This continues until every unit is assigned exactly once. If only 12 minutes remain at the end of the manga, a shorter final part is allowed. The number of chapters per part varies with dialogue density and story pacing.

Frozen part scopes store their member units and text hashes. Completed parts retain stable part numbers and upload receipts. Pausing, changing API keys or restarting the worker does not regroup those parts. Changing `part_minutes` changes future, unfrozen scopes.

The current Drive account has finite storage. The bot preserves the archive by default and stops safely on storage failure. It does not silently delete already uploaded videos or upscale assets to manufacture more capacity. A long book and accumulated daily videos may need an explicit retention/storage plan.

## First production run

1. Edit `config/manga.json`, replace the example URL with the real WeebCentral series link, and set your title, priority and part duration.
2. Commit the file. CI checks the list and route configuration without API requests.
3. Open Actions > Daily manga worker > Run workflow. Leave manga_url empty to use the list, and turn dry_run off.
4. The daily run at 13:17 Pakistan time continues the saved library. Lower priority numbers run first. One successful upload is allowed per run by default, with private visibility.
5. Read detailed progress, waits and usage in the private Drive dashboard/REPORT and receipts. The public Actions report contains safe connection checks and generic run status.

Daily target minutes are a planning goal, not a promise of quota or finished output. A complete hour-long cloud run and a real YouTube upload still need qualification. Free Colab GPU access and third-party free routes can be unavailable even when credentials are valid.
