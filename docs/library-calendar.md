# Library Calendar

Calendar is a read-only view of saved meeting metadata alongside Conversations, Search & ask and Analytics.

- Meeting day uses `started_at`, falling back to `created`, in Europe/Sofia. Audio imports already store the recording date in these fields. Date-only imports keep their literal date.
- Project selection is shared with Conversations; All projects and Unassigned have the same meaning in both views.
- Desktop shows a Monday-first month with meeting counts and a day agenda. Narrow screens show the agenda with day/month navigation. Dates use dd.mm.yyyy.
- Previous/next month preserve the day where possible and clamp at month end. Today uses the display timezone. Arrow keys move by day/week in the month; Page Up/Down move by month.
- URL stores day/project; Back, Forward and reload restore them. Opening a meeting uses the existing unsaved-edit guard.
- State events refresh counts, statuses and the visible agenda. Missing/invalid meeting dates are reported and remain reachable in Conversations.
- No model call, Google read, connector write or editing action is triggered by browsing. Existing outgoing Calendar sync is unchanged.

Google upcoming events are a later phase. Their source binding must distinguish account, calendar and recurring event instance from Atlanta's outgoing event binding. Starting a recording from a source event must never overwrite the original invitation.

Validation: `node tests/web_calendar_regressions.cjs` (also included in Python discovery). Browser QA uses disposable fictional meetings, not the user's library.
