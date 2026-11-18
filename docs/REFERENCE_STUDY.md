# Reference video analysis — language, story handling and visual support

Reference: https://www.youtube.com/watch?v=G7w2Co2pzU0

## What was actually reviewed

- The complete audio was downloaded: 10,370.021 seconds, approximately 2:52:50.
- Groq `whisper-large-v3-turbo` successfully transcribed all 18 intervals. Raw responses, source hashes, timestamps and request records are retained locally. An interrupted/resumed download had one damaged 19-second interval; it was recovered through a fresh source-audio download and inserted into decoded audio before the affected chunk was transcribed again. Three extra quality recheck uploads and one failed initial large upload are recorded; the final 18 source intervals all pass duration/hash checks. This replaces the earlier caption-only basis.
- The full transcript was profiled for language statistics. Close reading covered the opening ten minutes, selected dialogue/action/rule/transition passages across the remaining ten-minute intervals, and all 17 chunk joins. This is not a claim of manually reading every word or watching every frame of three hours.
- Visual review used 154 curated frames in 15 windows: the opening 0:00–1:58; windows beginning 2:00, 3:00, 4:30, 5:30, 6:30, 7:30, 8:30 and 9:30; windows at 1:00:00, 1:30:00, 2:00:00, 2:30:00 and 2:50:00; and the closing 2:52:00–2:52:49. Each middle window has eight frames spaced three seconds apart. These are sampled visual windows, not continuous full-video viewing.
- The five later 24-second clips and final 50-second clip were downloaded independently of the incomplete full-video download. Their container durations and zero start times were checked. Video sampling resolution is 854×480; it supports layout/content observations but not production-resolution sharpness claims.
- No audience retention data or original edit project was available. Reasons for effectiveness below are interpretations of the observed construction, not measured causal proof of viewer retention.

## Main finding

The reference makes a dense manga easy to follow by moving through the source's exchanges and thoughts in a clear order while the camera points to the relevant material. It does more than describe visible objects, but much of its apparent explanation is already written in the manga. The essential distinction is not explanation versus no explanation. It is **source-supplied meaning versus additional narrator interpretation**.

In several inspected passages, something that could sound like a narrator inventing a motive or feeling is supported by a visible thought balloon or narration box. For our pipeline, understanding the story is necessary to attribute that information correctly. Understanding does not authorize the AI to add missing motives, mechanisms, symbolism or answers.

## Measured language characteristics

After aligning shared text in the overlapping chunk boundaries and checking joins, the merged transcript contains approximately **35,871 words**. Average pace is **207.5 words per minute**; ten-minute windows range roughly **198.7–218.5**. Counts are approximate because ASR can mishear words and names, and boundary allocation is imperfect.

Whisper's inferred punctuation gives a median of **16 words** and a mean of **17.9 words** per sentence. These are ASR sentence boundaries, not a recovered authored script. Do not impose these values as quotas. The reliable observation from close reading is simpler clause construction and familiar subjects.

The most frequent ASR sentence starts include a pronoun for the main character (426 occurrences), his name (231), a definite article (98), and a female pronoun (89). Time and contrast openings also occur. The reference does not avoid repetition by constantly inventing new labels for characters. Repetition keeps the subject easy to track while the picture changes.

For comparison, the criticized automatic draft has **310 words in 13 punctuated sentences**, averaging **23.8 words per sentence**, delivered at approximately **192.1 words per minute**. Its first six sentences range from **23 to 34 words**. This supports the concern about crowded construction, but short sentences alone would not solve unnecessary interpretation or awkward selection.

## Timestamped narration–image comparisons

The narration column paraphrases the reference; it does not reproduce its script. Times identify reviewed windows, not exact authored sentence boundaries.

| Window | What narration carries | What is visible | What this establishes for our system |
|---|---|---|---|
| 0:08–0:12 | A mother's question about employment and her reason for asking | Kitchen setting, characters' positions and the father's future ability to work in printed dialogue | Preserve the question and its stated reason. The room and posture do not need separate descriptions. |
| 0:18–0:30 | The reply, the mother's response, and his leaving the exchange | Argument balloons followed by his actions and self-critical source text | Follow the exchange rather than interpreting the family dynamic. A response changes the situation; a pose can remain visual. |
| 1:22–1:30 | Why he wants to receive the delivery himself | Source narration/thought about giveaways and items he does not want his parents to see | A motive may belong in narration when the source supplies it. It is not an invitation to infer other motives from expressions. |
| 1:34–1:46 | His interpretation of the courier's look and other people's attention | A courier encounter, his appearance and printed speculation about how others see him | Keep the interpretation attached to the character. Do not turn the suspicion into a fact about what everyone thinks. |
| 2:00–2:21 | Identification of an item and the claims in an accompanying note | Item, note, reader and text-heavy source regions | Carry meaningful written content so viewers need not read it. Attribute a note's claim rather than endorsing it as world truth. |
| 3:00–3:21 | Starting an activity, encountering an attack, and a character's attempt to understand it | Interface/start action, carriage, attacking creatures and a person appealing for help | Concrete events provide momentum. There is no need for a separate paragraph declaring danger or explaining what an attack symbolizes. |
| 4:30–4:51 | A question about controls, an observation about text-based conversations, apology and subsequent exchange | Interface-related thoughts followed by dialogue groups | Background arrives at a relevant point. Shift the spoken focus when the source conversation shifts, not at every panel edge. |
| 5:30–5:51 | Doubt about an instruction system, a test action and its visible response | Source thoughts, typing/confirmation, then characters reacting to the resulting message | Attempt → result is a complete thread. The AI should not add an explanation of the underlying technology. |
| 6:30–6:51 | A practical limitation on using newly cut wood | Printed discussion and illustrated material/process | Keep the explanation that the manga actually supplies. Do not expand it into a woodworking lesson. |
| 7:30–7:51 | Uncertainty about how the activity progresses, followed by newly introduced rules | Questioning source text, map-like imagery and point/interface explanation | A question can remain open until the source answers it. A new rule belongs at its introduction, with scope and limitations intact. |
| 8:30–8:51 | Conversation about food, possible assistance and a concern about sending someone away | Dialogue, supplies and explicit planning thoughts | Tell the choice and the source-stated objection. Do not reduce this to facial reactions or make the narrator choose the best strategy. |
| 9:30–9:51 | A newly noticed payment option, conversion and the resulting resource constraint | Printed conversion information, possible rewards and a check of available resources | Numbers earn narration when they explain a decision. Inventory labels and every decorative detail need not be read. |
| 1:00:00–1:00:21 | A correction to the understood frequency of an action and a child's repeated activity | Source narration boxes, objects and the child doing that activity | Preserve corrections and exceptions. Compress routine repetition without inventing personal development beyond source-written observations. |
| 1:30:00–1:30:21 | A handover of action, attacks and the acting character's response | Character dialogue, combat panels and written thoughts | State meaningful action plainly. The artwork supplies speed, impact and pose; narration need not intensify each strike. |
| 2:00:00–2:00:21 | A character's question, a comparison with known rules and a new worry about availability | Book, source explanatory text and the character's own hypothetical concern | Distinguish a person's worry from an event that has happened. Keep source conditions rather than making the concern a prediction. |
| 2:30:00–2:30:21 | Work-related dialogue and concern about a colleague | Workers and an extended dialogue group about tiredness, rest and money | A useful exchange can remain on one focused group for several seconds. A new shot is not required for every clause. |
| 2:50:00–2:50:21 | Questions about a person's behavior and other unresolved possibilities | Explicit speculative questions in source thought text, followed by a departure exchange | Preserve questions as questions. The narrator does not need to solve the mystery to continue the recap. |
| 2:52:00–2:52:49 | Remaining questions, a final exchange and a closing reflection | Unresolved-question text, ordinary interaction and the manga's own closing narration boxes | The closing thematic connection is visibly supplied by the manga. This is an important exception to assuming every meaningful reflection is an AI-added interpretation. Preserve such a source ending when appropriate; do not manufacture one for every chapter. |

## Sentence and paragraph mechanics

### The subject stays easy to follow

The reference often starts with a character, an ordinary action, or a short time cue. It accepts repeated pronouns and names. This lets listeners spend attention on the event rather than decoding an elaborate sentence. Our current draft repeatedly opens by subordinating one event to another or attaching an interpretive reaction before the action. That makes it sound composed for reading aloud from a book.

The project should prefer a direct main clause without mechanically making every sentence identical. Time words and subordinate clauses remain useful. A change of subject or important new condition is a reason to split a sentence; a fixed word count is not.

### Speech and thoughts do the explanatory work

The reference frequently reports what someone asks, says, thinks, notices or considers. Those are distinct information sources. A character's reasoning can create a smooth connection without an omniscient narrator explaining what the scene means. In our system, the exact dialogue/thought field must remain distinguishable from the extractor's interpretive summary.

### The unit of flow is an exchange or decision

A useful passage can span several printed regions: a request, an answer, a limitation, and an action. Conversely, a page may contain more than one time or situation. The model needs enough context to follow that thread, but the recap should not verbalize the planning scaffold. It should not invent a motive or consequence simply to complete a scene-plan field.

### Mundane actions can connect larger developments

Quiet interaction, ordinary tasks and short transitions keep the story moving without constant intensity. The reference's appeal is not restricted to high-stakes scenes. Its working method transfers to conversations, rules, routines and action. This matters for testing: the violent opening alone is a poor benchmark for a general recap voice.

## Visual grammar and its relationship to narration

The sampled material repeatedly uses a white field, black-and-white art grouped like pages, border/shadow separation, vertical movement through adjacent regions, focused crops and changes of scale. Both small overview-like views and frame-filling details occur. The first seconds also include a colored stylized opening; this is not a reason to add a generic intro to Wabsa's videos.

At several sampled points, movement directs attention to the region carrying the current dialogue or thought. Neighboring material can remain partly visible, preserving context. Some sampled motion frames are blurred while settled frames are sharp. The result supports an inference of fast reframing with settling, but this study did not recover the animation curves, motion-blur settings or edit project.

The narration can paraphrase text while the viewer watches a face or action. Exact visual text remains available for optional inspection; reading it is not required to follow the exchange. This is the division of labor our earlier prompt missed when it asked for an audio-only account.

The samples show panel/group compositions as well as page-like views. They do not establish that the original editor always moved one intact full-page asset. Wabsa's desired whole-page 2D camera remains the project requirement. We can reproduce the attention-guiding relationship with that implementation without falsely claiming the reference's internal method is identical.

Shot holds vary with information. The 2:30:06–2:30:21 samples remain on the same dialogue group with small framing changes, while the action and rule passages move through more regions. A universal cut interval would lose this relationship. Future timing should align to spoken exchanges, actions and reveals, not word-count-only image durations or one shot per sentence.

## What plausibly creates engagement

1. The current situation is concrete, so a viewer can follow it without a long setup.
2. Source questions create the next reason to keep watching: an item's identity, an uncertain outcome, a limitation or a choice.
3. The answer usually produces another action or practical question instead of closing into an abstract explanation.
4. Camera attention reduces the effort of locating the relevant manga information.
5. Everyday scenes and consequential events share the same accessible voice, providing variation without a narrator continually announcing intensity.
6. Later meaning can arise from accumulated source events. The inspected ending reinforces that the manga itself can supply a reflection; the AI does not need to manufacture a moral.

These are explanatory hypotheses about the craft. They are not verified claims about audience metrics.

## What should not be copied blindly

The transcript contains emotional amplification, repeated surprise, formal speech tags, participial openings and occasional source-layout commentary. Automatic recognition also produces inconsistent names and mistakes a recurring social label for an ordinary word. The 6:00–6:30 passage repeats astonishment in several forms; that conflicts with Wabsa's preference for restraint even though it occurs in the reference.

The reference is therefore a positive guide to progression and accessibility, with explicit editorial overrides. A rule that bans every emotional word would also be wrong: some emotional content is written in the source and changes what a character does. The target is necessary meaning in ordinary language, without extra psychological narration.

## Why the current automatic sample missed the target

- The actual writer request contained the current and prior evidence, but no reference excerpts or calibrated examples.
- Its evidence summaries already included dramatic descriptions. The writer was not sufficiently required to separate those summaries from source text.
- The active instruction assumed the audience might not see the images, encouraging redundant description.
- Coverage requirements and a small sentence allowance per segment encouraged dense clauses.
- The critic emphasized factual coverage and had no comparably concrete spoken-style rubric.
- Successful structural validation was a technical check, not demonstrated editorial approval.

## Deliverables and next validation

`../../REFERENCE_STYLE_BIBLE.md` converts this study into detailed rules for selection, sentence flow, uncertainty, emotion, dialogue, transitions and visual sharing. Original calibration cases illustrate the rules without copying the reference's script or importing its story into the manga. `narration_style.txt` is the compact executable contract; the writer and critic must use compatible standards.

No automatic generation should be declared consistent merely because this analysis is complete. The criticized opening is development material. The next quality comparison needs unedited AI outputs on new conversation, action, rule, quiet-transition and unresolved-event scenes, with the prompt/model/request record retained. Images need not be reread simply to test wording against unchanged evidence.
