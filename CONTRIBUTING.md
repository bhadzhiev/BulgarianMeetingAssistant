# Contributing

Thank you for your help. This guide tells you how to propose a change.

## Rules for the `main` branch

- Change `main` only through a pull request (PR). Direct pushes are blocked.
- The code owner (@bhadzhiev, see `.github/CODEOWNERS`) must approve each PR.
- A new push to a PR removes the earlier approval. Ask for a new review.
- Force pushes and deletion of `main` are blocked.

## Set up the project

You need macOS 13 or later on Apple Silicon, Python 3.11 or later, ffmpeg, and the Xcode Command Line Tools.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
brew install ffmpeg
./build_native.sh
```

Start the app with `.venv/bin/python desktop_app.py`. To keep your own meetings safe, use a separate
library for development:

```sh
.venv/bin/python desktop_app.py --port 8799 --library /tmp/meeting-dev --backups /tmp/meeting-dev-backups
```

## Make a change

1. Create a branch from `main`. Use a short name, for example `fix-task-filter`.
2. Make one change per PR. Keep the PR small.
3. Write code that looks like the code around it: the same names, idioms, and comment style.
4. Add or update tests for each change in behavior. The tests are in `tests/`.
5. Run all tests. All tests must pass:

   ```sh
   .venv/bin/python -m unittest
   ```

6. For a change in the web interface (`web/`), open the app and check the change in a browser.
   Describe what you checked in the PR.
7. Update `README.md` when a change affects what a user sees or does.

## Protect privacy

This app records meetings. The data belongs to real people.

- Do not commit the `meetings/`, `models/`, `backups/` or `bin/` folders. `.gitignore` excludes them.
- Do not put real names, recordings, transcripts, or notes from real meetings into code, tests, or
  screenshots. Use made-up names and text.
- Do not commit API keys, tokens, or `google_oauth_client.json`.
- Do not add a feature that sends audio or text to a cloud service without a clear setting and a
  message in the interface.

## Write the PR

- Give the PR a short title that tells what changes, for example "Fix blank owner filter".
- In the description, tell what changed, why, and how you tested it.
- Tell the reviewer about known limits or steps that you did not test.

## Writing style

Write documentation, comments, and messages in simple English: short sentences, one idea per sentence,
active voice, and the present tense.

## Report a problem

Open a GitHub issue. Tell us the steps to repeat the problem, what you expected, and what happened.
Remove private meeting content from logs and screenshots before you attach them.
