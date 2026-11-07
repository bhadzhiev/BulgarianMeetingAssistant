# Automatic AI titles and Google Calendar

## Automatic AI titles and Google Calendar

Leave the meeting name blank to let AI name it from the final transcript (or the saved
live draft when final processing is disabled/unavailable). Names you type are preserved.
In **Settings → Automatic meeting titles**, choose **Configured API** or **Cloud · OpenAI**.
Local titles use the shared Local AI model; cloud titles have their own model setting. Title generation is independent of meeting notes; it works when notes are off.
Cloud titles send bounded transcript excerpts to OpenAI. If the model is unavailable or
there is no recognized speech, the original name remains and the meeting shows the reason.
Use **Generate AI title** on a saved meeting to retry or explicitly replace a manual name.
You can always use **Rename** afterward. Manual edits made while AI is running take priority.

To connect a calendar:

1. Open **Settings → Google Calendar** and click **Sign in with Google**.
2. Sign in and allow Calendar access in your browser. Then return to the app.
3. The app selects your primary calendar. Choose a different **Destination calendar** if
   necessary. Only calendars with writer/owner access appear.
4. Enable **Add every new meeting to this calendar** and click **Save settings**.

Use **Switch Google account** or **Sign out** to change the account. The app keeps tokens
in **macOS Keychain**, not in meeting or settings files.

**One-time app owner setup.** Google requires an OAuth client for each app, also for
"Sign in with Google". Do this one time for your copy of the app:

1. In a Google Cloud project, enable **Google Calendar API**.
2. Configure the OAuth consent screen. Add your accounts as test users, or publish the app.
3. Create an **OAuth client ID** of type **Desktop app** and download its JSON.
4. Save the JSON as `google_oauth_client.json` in the project folder, next to `desktop_app.py`.
   As an alternative, set `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`.
5. Restart the app.

After this setup, people only click **Sign in with Google**. The file is in `.gitignore`.
For a Desktop app client, Google does not treat the client secret as confidential.
**Settings → Google Calendar → Advanced** still accepts a client JSON file. A client
imported there has priority over `google_oauth_client.json`.

The app requests calendar-list read access and calendar-event write access. It uses desktop
OAuth with a loopback callback, PKCE S256, expiring single-use state, and background refresh.
Google test-mode credentials or Workspace policy may require reconnecting later. Details:
[Google desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app) and
[Google Calendar event creation](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert).

After a recording is saved, the app creates a historical calendar event using the actual
start/end wall-clock times, including pauses. Google receives the **title, time, and local
meeting link**; this integration does not upload the audio, transcript, notes, or API keys.
If an AI title is still pending, the event initially uses the current name, then updates.
No attendees are added, no invitations or reminders are requested, and the event is marked
as not blocking availability. Visibility follows the destination calendar's settings.

Links look like `http://127.0.0.1:8765/?meeting=<id>`. They open the saved meeting **on this
Mac only**, while the app runs at that address. They contain no app session credential.
A browser without the app session gets a page that opens `atlanta://meeting/<id>` in the
desktop window. If the app is closed, start it first, then open the calendar link again. Links are not public sharing links and will not open the
recording from your phone or another computer. Keep the normal app port (8765) for stable links.

Calendar events use a stable ID and app ownership marker. Retries, AI title updates, and
renaming update the same event. Each meeting keeps its original calendar/account binding;
changing the default calendar affects future meetings. If another Google account is
connected, the app refuses to update an event bound to the old account. Existing events
are never moved or deleted automatically. They are deleted only when you delete the meeting
and confirm the event deletion.

To add older recordings after configuring the destination, click **Sync saved meetings**
in Settings, or **Sync to Google Calendar** in a saved meeting. Repeating either action
updates existing events instead of creating duplicates. Normal recording/processing
status is separate from calendar/title status. Failed calendar writes are retained with
an error and retried up to three times (after 1, 5, and 15 minutes), including after an app
restart. The meeting's sync button provides an explicit retry. **Sign out** removes local
user tokens and attempts Google token revocation; the client configuration remains.

Google OAuth, token refresh, event writes, conflict handling, account changes, AI naming,
and browser deep links are tested with isolated fakes. The production connection and
macOS Keychain prompts require your actual client JSON, Google sign-in, and chosen calendar;
no live event creation has been verified as part of this setup.
