# UI readability pass · 2026-11-06

Based on main at 0d78da1 and a synthetic library with long Bulgarian meeting/task titles.

- Project Timeline uses available space for linked stages. Missing stages become a short footer rather than empty columns. Full titles wrap below the type label; no two-line truncation or 780px minimum grid.
- Linked work / Activity labels explain the two timeline views. Task nodes open the same task card directly. More than six links in a stage can be expanded and collapsed with an accessible button.
- Related message, reader, Google, backup, link and notes actions wrap with explicit gaps. Review confirmation links wrap independently of their explanation. Small input/button rows and scope controls do not force their contents off-screen.
- Task owners use person initials, without transcript-only NEW speaker badges. Task history and Import use shorter, accurate instructions.
- Fixed meeting task history failing because its transcript reader was imported from the wrong module. A real meeting/source regression checks that evidence loads without changing the task or making network requests.

Verification: 896 Python tests OK (1 skipped), all web regression scripts including new trace flow checks, JS syntax and diff whitespace checks. Synthetic desktop UI exercised Capture, Import, Calendar, My Work/task cards, Settings, GitHub draft, and project Timeline. GitHub publishing and AI generation were not invoked.

Timeline measurements (CSS px):

| Viewport | Document width | Trace card width/scroll width | Clipped titles |
| --- | --- | --- | --- |
| 390 × 844 | 390 | 322 / 322 | 0 |
| 900 × 900 | 900 | 736 / 736 | 0 |
| 1440 × 900 | 1440 | 1056 / 1056 | 0 |

At 390 × 844, Capture's Start bottom is 821px; New task and Settings have equal client/scroll widths (352px); GitHub draft also has equal widths and a 293px-high text editor. Synthetic data checks are not an audit of every possible integration payload or long-text combination.
