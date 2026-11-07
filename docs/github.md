# GitHub: repositories, drafts and changes

## People, project repositories and GitHub drafts

Atlanta keeps the conversation and its evidence; GitHub keeps the work. Atlanta does not write to
GitHub. You copy a draft, or open GitHub with it filled in, and publish it yourself.

- **People** (Settings → People): a person joins one real person's name, other names that appear in
  transcripts and as task owners, emails and a GitHub username. **Check on GitHub** saves the stable
  GitHub user ID (a read-only `GET /users/{login}`), so a renamed account stays the same person. Names
  and GitHub accounts belong to one person only. Nothing is guessed from a voice. Emails stay on this
  Mac and never enter GitHub text. A person shows what they said (transcript rows with one of their
  names) and what they took on. **Only a task whose owner a person confirmed is a commitment.** An owner
  from the AI shows as "AI suggestion · Confirm"; saving the same owner confirms it and adds a history
  entry. Unconfirmed owners are listed apart and never reach GitHub drafts.
- **Project repositories** (Projects → Overview): a project lists its GitHub repositories. One
  repository can belong to several projects. Drafts and links offer these repositories first.
- **Copy as issue / comment** (GitHub ▾ on a task, decision or question, and on a saved excerpt): the
  draft has the text, the project, the quoted transcript moment with its date and time, a confirmed
  owner (as `@login` when the person has a GitHub username) and due date, and an Atlanta reference
  (`<!-- atlanta:resource=item:… -->`). Meeting titles are included by default and speaker names are
  hidden by default; both are switches. You can edit the text before you copy it. **Open on GitHub**
  opens the new-issue page of the chosen repository with the title and text filled in. If the item has
  no project, the draft asks you to choose one. If the project has no repository, the draft shows the
  repository editor, so you can link one without leaving the dialog.
- **Assignee** (issue drafts): choose a person from Atlanta who has a GitHub username. The confirmed
  owner of the task is the default. The issue is created with this assignee, and **Open on GitHub**
  fills it in too. Add GitHub usernames in **Settings → People**. GitHub accepts only people who can
  be assigned in the repository; otherwise publication fails and shows the reason from GitHub.
- **Label**: every issue that Atlanta creates gets the label `created by ATLANTA`, also through **Open
  on GitHub**. If the label does not exist yet, GitHub normally creates it with a default colour. Comments get no label.
- **Link existing issue or PR**: enter `#123`, `owner/name#123`, a GitHub URL, or words of a title from
  the GitHub cache. The link lives only on this Mac; GitHub does not know about it unless the published
  text includes the Atlanta reference. A link is checked against the GitHub cache, then with a
  read-only request; offline it is saved as "not checked". Linked issues and PRs appear in the project
  trace and events, and an open issue in My Work → GitHub lists the Atlanta resources linked to it.

`people.json` and `github-links.json` are in library archives; restore adds the archived ones that this
library does not have.

## GitHub changes by period

Open **My Work → GitHub → Changes by period**. Enter one repository, an optional branch
(default: the repository's default branch), and From/Through dates. Dates use **Europe/Sofia**;
the default is yesterday at 00:00 through now. Historical end dates include that entire day.
Periods are limited to 31 days.

**Collect changes** reads GitHub without sending code to AI. Private repositories need
**Contents: Read-only** and **Pull requests: Read-only** on the connected fine-grained token.
Collection pins the branch head SHA, gathers merged PRs by merge time and other reachable
commits by committer time, and avoids reporting a PR and its commits twice. These timestamps
do not reconstruct historical push times or prove that a change was deployed.

The report stores commit/PR descriptions, available patches and bounded context from selected
code files. It lists omitted binary, generated, sensitive-name and oversized files. Limits are
30 PRs, 60 dated commits, 80 text files and 160 collected evidence parts; AI reads at most 80
parts. Patch/context and GitHub pagination limits remain visible as partial coverage. This is
not a full-repository audit, CI execution, deployment verification or a security guarantee.

**Analyze with AI** previews the exact endpoint/model, reasoning/output limit and input size.
Approve explicitly before the saved code snapshot leaves the app process. The configured
notes provider selects Local API or OpenAI; there is no automatic fallback. Repository content
is untrusted data, not instructions. Analysis runs in an isolated cancellable worker with
bounded inputs, splitting on output truncation. Each finding needs an exact source quote and
a saved evidence ID. Findings are AI interpretations that need review, even with valid quotes.

Completed collection/AI parts are saved. Continue explicitly after interruption; a crash or
restart never resumes an AI export automatically. Unchanged commit snapshots and completed
analysis parts can be reused. Recording or meeting processing pauses repository jobs.
**Suggest a task** asks the selected LLM to draft a task from the finding and its evidence.
Review/edit the draft, then **Create task** creates an open local task. Cancel creates nothing. Existing task statuses are never completed from code automatically. Reports can be
linked to a meeting without editing that meeting's transcript or notes.

Reports stay in `repo-reports.json`, are included in Archive/Restore, and are capped at 24.
Existing reports are not overwritten by restore. Delete one report or use **Clear all local
repository reports** under About GitHub; the latter works after disconnecting too. Promoted
WorkItem evidence snapshots and previous archives remain. No automatic retention purge runs.

## GitHub: repositories, open issues and pull requests

Open **My Work → GitHub**. Create a **fine-grained personal access token** for the selected repositories,
then Connect. Give it these repository permissions:

- **Issues: Read and write**, if you want to create issues or comments from Atlanta. **Read-only** is
  enough to only read issues; publication then fails with HTTP 403.
- **Pull requests: Read-only**.
- **Metadata: Read-only** (GitHub adds it automatically).

For an organization repository, set **Resource owner** to the organization. If the organization
approves tokens, an owner must approve the token, and also each later change of its permissions.
To fix a 403 after publication, edit the same token on GitHub. You do not need to connect it again.
The app verifies the account with GitHub and stores the token in the shared Atlanta macOS Keychain vault.
It does not reuse `gh` credentials or environment tokens. The token input clears after submission;
status, settings, archives and command arguments never include it. Token creation, organization
approval and SSO remain GitHub/account-owner setup. See
[GitHub token permissions](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens).
The sync adapter only makes GET requests. Creating an issue or comment additionally requires **Issues: Read and write** for the target repository and any organization approval. A refused publication shows the message from GitHub and, when GitHub sends it, the permission that it needs. Publication is a separate, explicitly approved POST; metadata access and repository user-role permissions do not prove that the token can publish.

Project repository choices use a separate paginated `GET /user/repos` listing (100 per page),
including owner, collaborator and organization-member affiliations visible to the token. Open
**Project settings & repositories** to load the list, or choose **Refresh repositories**.
A complete successful refresh replaces the access snapshot, removing stale choices; failed,
interrupted or credential-changing refreshes keep the previous choices with a visible status.
The issue cache is only a fallback before the first complete listing. Discovery stops visibly
rather than claiming completeness above 100000 entries. Manual `owner/name` entries remain
possible offline; attaching one locally does not verify GitHub access. Project saves include
the previous repository list to reject stale edits and freeze the editor while saving.

After Connect, the GitHub tab lists every open issue and pull request that the token can read, from all
repositories (`GET /issues`, at most 300 per filter, newest change first). You do not choose a repository
first. The first visit syncs the list. Choose **All open**, **Assigned to me**, **Created by me** or
**Mentioning me**; each filter keeps its own result set. Narrow the list by kind, repository or text.
**Sync** reads the list again. Open pull requests also read their PR record, so their revision matches
a single-item refresh.

The per-repository search sync (`/api/github/sync`) remains for compatibility. Each action handles at
most 20 search matches and at most 200 per repository/filter refresh. Search indexing can lag or report
incomplete results. This is not a full mirror or a webhook subscription; absence from the capped
results never proves deletion.

Open an item to read its cached Markdown as plain text and fetch time. PR states distinguish open,
closed without merge and merged; the PR detail is checked separately from the issue representation.
The cache uses the issue database ID returned by the Issues API for both issues and PRs, with the PR
ID retained separately. These IDs differ, as noted in
[GitHub's issue API](https://docs.github.com/en/rest/issues/issues). Stable source IDs survive repository
renames, although redirects are deliberately not followed with credentials: enter the current
repository path and restart its refresh. Login changes during a page sequence also need a restart.

**Suggest a task** generates an editable draft after approval of the shown AI provider.
**Create task** saves the edited text as an open local task with a quote and repository/number/kind
references. Cancel creates nothing; existing task fields and statuses stay unchanged. GitHub remains authoritative for the remote issue/PR state. A close or merge never
silently completes or reopens the local task. Observed source changes invalidate older pending
proposals; individual **Refresh this issue / PR** rechecks the object. Access loss blocks new
acceptance and clears cached text; historical quotes remain. Rate limits halt without inferring
that the repository was deleted. There are no GitHub writes, AI exports, comments, diffs, code reads
or automatic task executions in this pilot.

The indexed `github-cache.sqlite3` is per verified GitHub user ID and excluded from library archives;
promoted sources remain in the portable WorkItem graph. Lists show at most 200 matches for the current
filter generation. Cache records can accumulate across filters/refreshes until cleared. Clear cache
can remove an old identity after disconnect and keeps source snapshots/archives. **Disconnect locally**
removes the local Keychain credential; revoke the token separately on GitHub if needed. Cancelling,
recording/processing and account changes stop further work, with an in-flight request taking up to
30 seconds. No automatic background sync, OAuth app registration or GitHub Enterprise host is supported.

Tests use synthetic GitHub data and an in-memory token store. Real token permissions/organization
approval, live repository behavior and actual Keychain prompts still need account-owner validation.
