# Capacity planning

These figures describe configured client ceilings, not a quota promise from the providers. Google enforces requests, tokens and other limits per project. Multiple keys in the same project do not multiply those limits. Account labels remain provisional until provider metadata establishes their project scopes.

| Stage | Configured daily ceiling per Google quota group | Four independent groups, if entitled |
|---|---:|---:|
| Reader route | 440 requests, extraction batches of 2 pages | At most 3,520 extraction pages if no allowance were used on other reader tasks |
| Writing | 18 requests, units capped at 40 pages | 72 requests; at most 2,880 pages if every unit fills the cap |
| Speech | 9 requests, batches capped at 2,200 words | 36 requests, at most 79,200 words |

Reader allowance also pays for subject geometry and phrase-focus planning, so the extraction-only page figure overstates actual end-to-end page capacity. Short chapters, oversized images and revisions can also reduce the writer's page ceiling.

At the configured 207 words/minute, 79,200 words corresponds to about **6.38 hours of narration**. A live 2,200-word speech sample produced 649.12 seconds (10.82 minutes) in 125.3 seconds, close to this estimate. It reported 18,905 total tokens. This does not establish sustained capacity. Short batches at part boundaries, revisions, failed calls, token limits and service availability reduce usable output.

A 45–60-minute part needs approximately 9,315–12,420 words and at least 5–6 full speech requests. A two-hour video needs approximately 24,840 words and at least 12 full speech requests. Those counts exclude retries and partially filled batches. Reading and writing demand varies with the source; there is no fixed chapter-to-minute conversion.

The NIM writer route permits 100 requests/day locally, within a shared provider ceiling of 500. OpenRouter permits 50 requests/day across the deployment; the seven credentials do not imply seven separate free-model allowances. Neither writer fallback adds speech capacity.

The worker runs for up to four hours per dispatch and currently uploads at most one finished video per run, privately. Its output duration is independent of that processing-time limit. GPU availability, download access, checkpoint transfer time, render speed and available Drive storage also constrain daily production. Keep one 45–60-minute upload as the initial qualification target before claiming several hours of reliable unattended output.

The earlier Isekai pilot used 36 source pages for 1,250 spoken words and 362.33 seconds of video. Linear extrapolation would be roughly 358 pages/hour, but that is one unit, not a proven general conversion. Its full local collection has 1,897 pages; the earlier extraction stopped at 64 pages and one rendered unit after reader service failures. Those original outputs remain preserved separately from the new cloud library.

The revised 720p30 visual pilot rendered 362.33 seconds in about 271.5 seconds on the local CPU, including encoding and verification. Cloud CPU performance and GPU upscale speed have not been benchmarked. Camera rendering uses CPU; the Colab GPU performs ESRGAN upscaling. Free Colab GPU availability is not guaranteed. Standard public Linux runner usage is subject to [GitHub's billing rules](https://docs.github.com/en/actions/concepts/billing-and-usage) and [limits](https://docs.github.com/en/actions/reference/limits).

The private Drive dashboard and request receipts record actual production use, model, credential label, reported tokens, holds and retry times. Empty production counters do not prove unused quota: prior development requests and other applications can consume provider allowance outside this ledger. A server limit response takes precedence over these planning figures.

The first production dispatch after adding the queue stopped on a storage failure before content generation was observed. Inspection found Drive request-rate exhaustion associated with rclone's shared OAuth app. The owner's existing OAuth app was enabled for Drive and authorized against the existing archive; its connection replaced the GitHub secret. Storage failures now expose only an allowlisted cause in the public report, with raw connection details kept private. This repair still requires a successful full production run to qualify.

Sources: [Google rate limits](https://ai.google.dev/gemini-api/docs/rate-limits), [rclone shared-client retirement and own-client setup](https://rclone.org/drive/#making-your-own-client-id). Active local limits are in [settings](../config/settings.json); earlier measured tests are in [verified status](VERIFIED_STATUS.md).
