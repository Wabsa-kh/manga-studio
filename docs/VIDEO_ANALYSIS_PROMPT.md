# Prompt for the video analysis model

Upload a 3–5-minute portion of the reference video containing quiet dialogue, action, panel-to-panel movement and several page changes. If possible also upload our latest preview as a second, clearly named file. Preserve the video audio. Paste the prompt below. More than one excerpt is useful, but analyze only what you can actually see.

---

You are analyzing a manga recap video's visual editing to help implement a deterministic, configurable camera renderer. Watch the attached reference closely, including the motion between settled frames. Do not summarize the manga story or rewrite its narration. If there is a second file called OUR PREVIEW, compare it separately against REFERENCE.

We want character/action-focused framing, an immersive white-paper setting, brief purposeful travel between panels, longer useful holds, subtle 3D page movement and transitions that keep pace with narration. We render intact manga pages, moving a camera across them; we do not require permanent cuts into separate panel images. Do not assume the reference uses that same internal technique.

Distinguish (A) directly visible observations, (B) estimates with confidence, and (C) implementation recommendations. Never claim to recover an exact easing curve, focal length, yaw angle, frame rate, software, shader or keyframe without evidence. Say when an effect could equally be 2D skew/scale instead of genuine 3D rotation. Use approximate ranges when measurements cannot be exact. Do not invent footage, sound effects or timecodes. If your video sampling misses short transitions, say so and identify the interval for closer inspection.

1. Give a timestamped shot-and-motion ledger for at least 15–25 representative beats, or every beat if the excerpt is shorter. For each record include start/end time, what the viewer sees, the speaking/thinking/acting subject, the narration topic, the camera's initial and final framing, and whether the focus is a face, body/group, action, object, text or setting. Explain WHY a text-focused shot is appropriate when it occurs. Record whether a visual reveal arrives early, with the spoken phrase or after it. Do not count each sentence as a new shot automatically.

2. Separate a beat into travel, settling, hold and subtle drift. Estimate their durations in seconds and the travel/hold proportion. Identify acceleration, peak-speed portion, deceleration, any overshoot, and whether pan and zoom occur together. Compare quiet conversation with action and discovery. Give at least five specific examples with timecodes, including an effective long hold. Does the editor spend most time moving or dwelling on useful art? Does the camera ever deliberately remain still?

3. Measure framing using normalized coordinates: [left, top, width, height] relative to the VIDEO frame, 0–1. At 8–12 settled frames give the visible artwork bounds, subject/face bounds, approximate headroom and side margins, and how much neighboring panel context remains. Use the same coordinate convention throughout. Estimate relative zoom only between views of the SAME original artwork. Do not compare absolute zoom numbers across unrelated pages. Describe clipping of faces, hands, speech bubbles and panel borders. Does the white background continue the page paper seamlessly, or is there a distinct boundary? If you can sample colors, give approximate RGB values and uncertainty; otherwise describe them without fake RGB precision.

4. Analyze the subtle 3D impression. Look at page-edge angles, relative lengths of opposite edges, parallelism of panel borders, changing corner positions and whether artwork shifts together as a plane. Distinguish Y-axis yaw, X-axis tilt, in-plane rotation, simple translation and 2D shear. For clear examples give a timestamp interval and estimate a plausible SMALL parameter range. Describe speed, direction changes and whether movement resets at page changes. Note when there is no convincing perspective evidence. Do not recommend strong warping, head bobbing or a continuously oscillating camera just to make it dynamic.

5. Inventory transitions: cuts, crossfades, paper/directional wipes, push/pan handoffs or others actually visible. For each type provide timecodes, approximate duration, direction, feather/blur, overlap behavior, audio relationship and when it is used. Does the old page move, does the new one move, or does a mask reveal it? Distinguish a camera moving within a page from an actual transition between assets. Check whether fades create a long distracting double exposure. Describe any transition sound only if audible; separate it from narration and music.

6. Diagnose motion quality. Look for pixel stepping, uneven velocity, shimmer on thin ink lines, repeated frames, abrupt changes of direction or scale, excessive motion blur, unwanted white/black flashes and poorly timed focus changes. If OUR PREVIEW is supplied, list its five most important differences from the reference with paired timecodes. Be precise about the visible defect; do not just say “make it smoother” or “more cinematic.” Do not claim a technical cause solely from appearance.

7. Turn the observations into 4–6 reusable presets: quiet exchange, character reaction, action reveal, meaningful object/document, panel handoff and page transition. For each provide reasonable configurable ranges for travel seconds, minimum hold, drift amplitude as a fraction of frame width/height, zoom change percent, yaw/tilt range if supported, easing description, transition duration/direction and any justified blur. Separate observed reference ranges from your recommended starting values. Add rules for choosing presets from narration and source events. Keep variation purposeful and deterministic rather than random.

8. Return a compact machine-readable JSON example after your written findings. Use:
{
  "coordinate_space": "video_frame_normalized_xywh",
  "evidence": [{"start_s": 0.0, "end_s": 0.0, "focus": "character|action|object|text|setting", "travel_s": null, "hold_s": null, "art_bounds": null, "subject_bounds": null, "motion": "description", "transition": "description", "confidence": "high|medium|low", "uncertain": []}],
  "presets": [{"name": "...", "travel_s_range": [0.0,0.0], "hold_s_range": [0.0,0.0], "drift_frame_fraction_range": [0.0,0.0], "relative_zoom_change_percent_range": [0.0,0.0], "yaw_degrees_range": null, "transition_s_range": [0.0,0.0], "basis": "observed|recommended"}],
  "priority_changes_for_our_renderer": [],
  "cannot_determine_from_this_clip": []
}
Use null for anything you cannot estimate reliably. End with the exact additional timestamps or closer samples that would resolve remaining uncertainties.
