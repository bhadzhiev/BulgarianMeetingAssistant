# Bulgarian quality check

Use consented 2–5 minute samples from: quiet table meeting, distant speakers,
noisy room, online call with headphones, and mixed Bulgarian/English technical terms.
Record the microphone/model/provider, Mac model and RAM, processing time, and audio duration.

1. Transcribe the same recording locally, export its transcript JSON, then repeat with cloud.
2. Manually correct a reference transcript against the original audio, without looking at model scores.
3. Run `python benchmarks/evaluate.py reference.txt local.json cloud.json`.
4. Review names, numbers, dates, omissions, and invented speech separately. WER alone is insufficient.
5. Review extracted decisions/tasks against the recording: correct owner, deadline, evidence, and whether the task was actually agreed.
6. For each capture mode, test pause/resume, a 60 minute session, microphone disconnect,
   process interruption, and recovery. Check track alignment at the start and end.

No real audio samples or provider rankings are bundled. The test suite uses synthetic audio;
it does not establish recognition accuracy or real microphone stability.
