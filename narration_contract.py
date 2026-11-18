"""One reference-calibrated contract for current and legacy writing/review calls."""
import json
from pathlib import Path
from narrative_continuity import CONTINUITY_WRITING_RULES,CONTINUITY_CRITIC_RULES

ROOT=Path(__file__).resolve().parent

def writer_style():
    rules=(ROOT/'narration_style.txt').read_text(encoding='utf-8')
    examples=json.loads((ROOT/'reference/style-calibration.json').read_text(encoding='utf-8'))
    return rules+CONTINUITY_WRITING_RULES+'\nREFERENCE CALIBRATION (style only; never current-story evidence):\n'+json.dumps(examples,ensure_ascii=False)

def critic_style():
    return '''\nSPOKEN-STYLE REVIEW — same audience contract as the writer:
    The viewer sees the artwork and should not need to read its written text.
    This is a casual recap, not an audio-only adaptation, literary interpretation or
    psychological explanation. Preserve source dialogue, thoughts and conditions.
    Keep source-written reasoning; do not demand that every event be explained.
    Do not recommend filling a source mystery, motive or causal gap. A claim in
    extraction meaning is not automatically an explicit source claim. Distinguish
    original text, concrete observations and the extractor's descriptive language.
    Flag unnecessary expression/posture narration, repeated or amplified emotions,
    formal reporting verbs that add force, ornate front-loaded constructions,
    crowded clauses and ambiguous pronouns when they impair easy spoken flow.
    A repeated clear name/pronoun is fine. Do not demand synonyms, equal sentence
    lengths, constant shot changes, a reaction to every line, or a fixed grammar.
    Flag essential text left for the viewer to read. Do not flag omission of an
    incidental visible detail merely because it appears in the evidence.
    Treat source-supplied beliefs as beliefs and source-supplied explanations as
    explanations. Do not remove meaningful thoughts or reasons in pursuit of brevity.
    For each real style failure, identify the segment and explain the specific
    listening problem under category=style when that category exists in the schema.
    Do not invent a quota of issues. Do not approve style on source-ID validity alone.
    '''+CONTINUITY_CRITIC_RULES
