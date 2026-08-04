---
description: Update project docs and push all changes to close out a session
---

Close out the current working session on this project:

1. Review everything built or changed this session (`git diff`, `git status`,
   and the conversation itself).
2. Update `docs/ARCHITECTURE.md` to reflect the current state of the
   system — not what was planned, what's actually there now.
3. Update `docs/INTERVIEW_PREP.md` with a new section for any feature
   completed this session, following the "Interview Prep Document" rule
   in CLAUDE.md.
4. Update `docs/pipeline-status.html`: mark newly completed steps as
   done, leave the rest pending, matching the page's existing visual
   format and style.
5. Append a new dated entry to `docs/PROGRESS.md`: what was built, what I
   struggled with, what to revisit, what's next. Never rewrite past
   entries — this file is a history log, not a current-state snapshot.
6. Write any new ADRs for significant decisions made this session, in
   `docs/adr/ADR-XXX-name.md`.
7. Stage and commit all of the above plus the session's code changes,
   then push to the remote. If no remote is configured, ask me for the
   repository URL first.
8. Confirm the commit and push actually happened by checking `git status`
   and `git log` — don't assume.
9. Give a short summary (5–10 lines) of what was updated and pushed.
