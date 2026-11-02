# Follow-up implementation

Prepare me now projects saved local work and linked GitHub evidence into a Follow-up card. It uses the last meeting of the selected type within the selected project or series as its comparison anchor.

- Completed tasks with no completion date stay in a separate group.
- No local edits since the anchor is a local history observation, never an assertion about remote activity.
- Confirmed blockers require a verified blocker statement; AI blocker statements appear separately for review.
- Open commitments, canonical questions, accepted/proposed decisions retain their WorkItem IDs. Superseded decisions are excluded.
- Each commitment includes its owner, matching local person reference, source moment, exact transcript segment when available, and local GitHub links.
- GitHub state carries cached/live/offline provenance and check time. Check GitHub now performs read-only updates; closed issues do not complete local work.
- Start next meeting fills context without recording automatically.

Automated regression coverage lives in tests/test_followup.py, tests/test_prepare.py and tests/test_briefing_completion_boundary.py. External writes and real client meetings were not used as QA. Hardware capture timing and human review-speed targets remain unmeasured. Browser and packaged-app validation must be performed before release.
