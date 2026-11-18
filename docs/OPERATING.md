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

Restore Drive state → import manga-list changes → choose the first enabled eligible book → download and verify original pages → upscale through Colab → read original pages → write source-linked narration with prior story memory → freeze a video part → generate speech and timing → render focused page-camera video → assemble and verify the part → checkpoint it to Drive → upload privately to the configured YouTube channel.

The downloader currently completes the requested book's chapter list before the upscale/reading stage. Upscaling currently completes before production starts. These stages are not a streaming chapter-by-chapter upload system yet.

Quota exhaustion saves successful work and a retry time. A later scheduled run resumes it. Finished videos can upload while AI generation is waiting. Invalid credentials, content rejections or ambiguous uploads may require review; no system can automatically guarantee completion for every rejection.

The private Drive checkpoint contains library.json, dashboard.json, REPORT.md, usage snapshots, request receipts, scripts, speech and completed media. The public Actions report shows connection booleans and generic run state.

# Keys and models

The production worker currently uses one GEMINI_API_KEY. Automatic API-key rotation and OpenRouter/NVIDIA routing are not enabled in this deployed adapter. The selected reader, writer and speech model names and conservative local request ceilings are in config/settings.json. Those ceilings are not a claim of actual account entitlement.

Changing Gemini keys within one Google project does not increase project quota. Separate-project routing needs verified project/credential mapping and separate budget accounting before it can be called working. See Google's official rate-limit documentation: https://ai.google.dev/gemini-api/docs/rate-limits . Google OAuth access credentials for Drive, Colab and YouTube refresh through their saved offline credentials; that is separate from rotating Gemini API keys.
