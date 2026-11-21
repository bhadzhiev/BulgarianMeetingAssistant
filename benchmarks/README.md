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

## Prompt request comparison

Run `python benchmarks/prompt_requests.py` for an offline report of request
counts and message sizes on 15 synthetic Bulgarian excerpts. Add both
`--base-url URL` and `--model MODEL` to collect real answers and provider token
usage. The optional credential comes from `ATLANTA_BENCHMARK_API_KEY`. Use
`--case N` for a single excerpt. The script never reads the Atlanta library.

Compare the current title and notes calls with the combined candidate, and
the split team analysis with the combined candidate. For notes, use the human
reference to score missed and invented commitments, owner and deadline, and
whether each cited moment supports its claim. For titles, check specificity
and support in the excerpt. For team analysis, check attribution, whether
quotes are exact and local to the cited moment, and whether both candidates
preserve supported observations. Record failures alongside time and tokens.
