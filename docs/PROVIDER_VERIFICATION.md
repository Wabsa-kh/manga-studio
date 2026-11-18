# Provider verification, 18 November 2026

The private credential pool contains four Google keys, seven OpenRouter keys and one NVIDIA key. Metadata authentication checks returned HTTP 200 for all twelve. Four small native Google generation requests completed using four different credential labels, proving live selection rotation. No API key values are present in this repository.

| Route | Actual test | Result |
|---|---|---|
| Google Gemini 3.5 Flash-Lite | Four small structured requests, one through each Google credential | All completed; approximately 2.6-8.0 seconds each |
| NIM Nemotron 3.5 Super VL | Current production writer schema, four pages of cached accepted Google evidence | Validated, 182 words, 52.03 seconds |
| Free OpenRouter Nemotron 3.5 Super VL | Same four pages of cached evidence and production writer checks | Validated, 183 words, 62.77 seconds |
| NIM reader | One original manga page, production schema | Format passed after dropping forbidden extra fields. Manual source inspection found incorrect speaker attribution and action descriptions. Kept out of default production reading. |
| Free OpenRouter Gemma 4 31B | Small structured control | HTTP 429; no quality conclusion and no key cycling to evade the shared limit |
| Google reader, later mixed-provider probe | Two-page original-image request | HTTP 503; known failure recorded without claiming an extraction |

The native NVIDIA model ID is `nvidia/nemotron-3.5-super-vl-120b-a12b`. The shorter name returned HTTP 404 and was corrected. OpenRouter uses its own ID, `nvidia/nemotron-3.5-super-vl:free`. Provider-specific IDs must not be assumed interchangeable.

NIM and OpenRouter writer results passed schema, source-reference, coverage and script checks. Four pages do not establish full-book quality or sustained throughput. The tested primary Gemini narration remains first in routing order. Native Gemini speech remains unchanged.

The new reader test's mistakes were not manually repaired into a claimed success. Schema projection removes only unsupported JSON properties; it does not change speaker identities, fix region guesses or rewrite the generated story. The factual shortcomings are why NIM reading is disabled by default.

Google project lookup identified one project using the connected owner account. The other credentials retain owner-reported separate-account scopes; numeric project IDs are not required. Actual quota responses can reveal shared project identities and trigger counter merging. No fixed daily-hour estimate is derived by multiplying key counts.

The free OpenRouter catalog was checked for zero token pricing. NIM uses its hosted trial endpoint. No paid fallback, credit purchase or billing enablement was added. A billing-dashboard audit of existing Google projects was not performed, so API responses alone are not presented as proof of a final monetary bill.

Tests cover persistent rotation, shared/project-scoped accounting, observed-scope merging, 401 quarantine, 429 handling, 503 fallback, no cross-provider replay after unknown acceptance, content-rejection holds, free-route enforcement, NIM async polling, pacing waits and long-manga part coverage. Live raw receipts and detailed source outputs remain outside this public repository.

All 87 tests passed in [GitHub Linux CI](https://github.com/Wabsa-kh/manga-studio/actions/runs/44377514940). The [model-pool worker check](https://github.com/Wabsa-kh/manga-studio/actions/runs/44374433057) loaded all twelve credentials and completed an empty-library Drive checkpoint run. The first complete cloud video and real YouTube upload still need qualification.

Sources: [Google quota scopes](https://ai.google.dev/gemini-api/docs/rate-limits), [OpenRouter limits](https://openrouter.ai/docs/api-reference/limits), [NVIDIA model endpoint](https://build.nvidia.com/nvidia/nemotron-3.5-super-vl-120b-a12b?section=deploy).
