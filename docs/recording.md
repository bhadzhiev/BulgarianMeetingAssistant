# Use the app and record meetings

## Find your way around

- **Sidebar:** New meeting, My Work, Library and Projects. **Library** holds Conversations, Search & ask
  and Analytics as tabs. **Prepare me** opens from a project (**Projects → Prepare me**) or from the
  project chip of a meeting. Without a chosen project, it starts with the project of the newest meeting
  that has one, or asks you to choose.
- **Back and Forward:** every view and tab has its own address. Use the ‹ › buttons in the top bar,
  ⌘[ and ⌘], or Alt+← and Alt+→. A reload keeps the view, the tab and the selected project.
- **Recording bar:** while a meeting records, a bar stays at the top of every other view. It shows the
  meeting, the time, the microphone level and a warning when the microphone drops out. It has
  Pause/Resume, Stop (it asks first) and a link back to the live transcript.
- **Needs attention:** an open meeting lists what still needs a person after processing, each with the
  step that resolves it: a processing error, speakers to name, new AI notes to review, notes to update
  after transcript edits, mentions that look like existing work, AI-proposed decisions to confirm, and
  tasks without an owner or a due date. When nothing is left, it offers **Prepare the next meeting**.
- **One decision state:** a decision shows one badge. **Proposed** waits for **Accept decision**.
  **Accepted** needs nothing. **Accepted · check again** means that the notes or the transcript changed
  after it was accepted; **Confirm decision** checks it again. **Hidden in My Work** asks for nothing.
  Needs attention counts the same states.
- **A confirmation holds:** an owner, a due date or a status that you set keeps the confirmation of
  that task. A new task in the meeting keeps the confirmations of the other items. New wording, new
  details, changed notes text or a changed transcript still ask for a new review.
- **Settings:** **Fast**, **Balanced**, **Best quality** and **Maximum privacy** fill the fields; nothing
  changes until **Save settings**. **Show advanced settings** reveals audio preparation, voice detection
  and the local AI response options. Closing Settings with unsaved changes asks first.
- **Action feedback:** an action that takes longer than a quarter of a second shows a spinner on its
  button, a thin bar at the top of the window and a status at the top that names it, for example
  "Save settings · in progress…". The status also shows above an open dialog, and for a save from a
  list or a checkbox. A long step names itself, for example "Importing the transcript and building analytics". A second press of the same button waits for the first
  action. A button that saved or started something shows a ✓ for a moment. An error shows in red.
- **Instant changes and Undo:** a checkbox or a list that saves at once shows what changed and an
  **Undo** button for 8 seconds. This applies to an answered question, the quick task fields (state,
  owner, due date, next follow-up), the project and destination in Review, and the series type and
  project color in Settings. A meeting with notes asks before its type changes: **Change type only**,
  **Change and make new notes**, or **Cancel**.

## Record an in-person meeting

The new meeting form shows the name, the meeting type and the microphone. Backup microphone, when to
transcribe, project and series, and the processing summary are under **More options**; its line shows
the current choices. The last meeting type and microphone are remembered. Before Start, chips show
whether the microphone, the system audio helper (online meetings), the transcription model and the
disk space are ready. Import is under **Recorded elsewhere?**, below the form.

1. Connect your iPhone as a macOS input device, or use the Mac microphone.
2. Enter a name, select **In person**, and choose the microphone.
3. Use **Test mic** for a ten-second level check. It does not save audio.
4. Choose **When to transcribe**: **After recording · no live captions** saves audio without
   running live Whisper, or **Live captions + final transcript after recording** shows a draft
   while you speak. Both modes use the full saved audio for the final pass; with Local transcription,
   that pass uses Whisper. Enabled spelling correction runs afterwards. This choice applies only
   to this meeting; Settings keeps the default for future meetings.
   Click **Start recording**. **Pause** discards audio until you resume and removes
   the pause from the saved timeline.
5. To mark a moment, press **1** (Important), **2** (Decision) or **3** (Check later), or click the
   buttons under the timer. Type a short note first if you want. Markers are saved in `markers.json`.
   After the meeting, **Moments you marked** at the top of the transcript plays each moment.
   Notes generation gets the markers as hints; the AI must still find the moment in the transcript.
6. Click **Stop & save**. The meeting appears in the library immediately; processing
   continues in the background when automatic processing is enabled. Otherwise choose **Transcribe**
   from the saved meeting. Disabling live captions does not disable the final transcription.

For the iPhone: use the same Apple Account on both devices, enable Wi-Fi/Bluetooth and
Continuity Camera, and confirm **iPhone Microphone** appears under macOS Sound → Input.
A cable can help maintain a stable connection. The app does not run on the iPhone itself.

## Import audio from a phone or another app

In **Import audio or a transcript**, choose an audio file (.m4a, .mp3, .wav, .aac, .ogg, .opus,
.flac, .webm, .mp4, .mov, .caf, .aiff, .amr, .3gp; up to 4 GB) and click **Import file**.
The app converts it with ffmpeg into the same 16 kHz mono `recording.wav` that a recording makes,
then processes it with the current settings. The meeting date comes from the recording time in
the file (iPhone Voice Memos write it), else from the file's modification time.
The file name is the meeting name until an AI title replaces it. The meeting appears only after
the conversion succeeds; an interrupted upload leaves nothing behind.

A transcript file (.md, .txt, .srt) skips the audio steps: transcription and speaker identification.
The meeting date comes from a date in the text. Without one, it comes from the date of the file: the file
is saved when the meeting ends, so the meeting starts its duration earlier. Pasted text gets today's date.
With **Process automatically** on, it then runs the same text steps as a recording: AI correction
(when it is on in Settings), then notes, tasks and decisions. A failed correction keeps the original
text and still makes the notes. The corrected segments can be restored, as after a recording.

## Настройки на Olympus WS-852 за най-добра транскрипция

Когато записваш с Olympus WS-852 и после импортираш файла, използвай тези настройки
(Rec Menu) — те дават на Whisper най-чистия изходен материал:

- **Rec Mode: MP3 128 kbps (стерео).** Най-високото качество на устройството. Режимите
  64/8 kbps mono орязват честоти, които Whisper използва. Приложението само конвертира до
  16 kHz mono при импорт, затова записвай в най-добрия наличен формат — около 69 часа на 4 GB.
- **Rec Level: High** за среща около маса (далечни или тихи гласове). **Low** само при
  диктовка на 5–10 см от микрофона. Избягвай Auto — изглаждането на нивата „помпира" шума
  от стаята и влошава разпознаването в тихите участъци.
- **Rec Scene: Off.** Докато е избрана сцена (Meeting, Conference…), настройките Rec Level,
  Rec Mode и Low Cut Filter са заключени. С Off запазваш ръчния контрол.
- **VCVA: Off.** Критично. Гласово-активираният запис паузира в тишината, реже началата на
  фразите и чупи хронологията — таймстемповете в транскрипта спират да съвпадат с реалното
  време, което засяга и маркерите, и разпознаването на говорители.
- **V-Sync. Rec: Off.** Същият проблем като VCVA.
- **Low Cut Filter: On** в стая с климатик, проектор или друго нискочестотно бръмчене.
  Гласът не се засяга. В тиха стая може и Off.
- **Noise Cancel, Voice Filter, Voice Balance** са само за възпроизвеждане и не променят
  файла — не влияят на транскрипцията.

При записа: разтвори вградената стойка (тя изолира вибрациите от масата), сложи
рекордера в центъра на масата далеч от лаптопи и вентилатори, не го мести по време на
запис и не го изключвай между репликите — един непрекъснат файл дава една чиста
хронология. За разпознаване на говорители (diarization) помага хората да са на различни
разстояния и посоки от микрофона. Файлът се прехвърля през вградения USB конектор и се
импортира през **Import audio**; датата на срещата се взема от времето на запис във файла.

## Record an online meeting

Choose **Online meeting** and your microphone. The app captures **all Mac system audio**
plus the selected microphone as independent tracks. Use headphones to avoid recording
remote voices twice through the microphone. Other Mac app sounds are included, so silence
unwanted notifications and avoid playing old recordings during capture.

System audio uses Apple's ScreenCaptureKit; no virtual audio driver is required. macOS may
request **Screen & System Audio Recording** permission for the launching app/helper.
Microphone capture also requires **Microphone** permission for the launching app/Python.
If capture is denied, grant permission in **System Settings → Privacy & Security**, quit
and reopen the launcher, then retry. The helper registers audio output only; it does not
save screen video. Capture cannot start on a Mac without an available display.

The app does not join meetings as a bot. It records what your Mac plays and what your
chosen microphone hears. ScreenCaptureKit reference:
[Apple capture sample](https://developer.apple.com/documentation/screencapturekit/capturing-screen-content-in-macos).
