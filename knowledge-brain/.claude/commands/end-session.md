---
description: Update project docs and push all changes to close out a session
---

Close out the current working session on this project:

1. Review everything built or changed this session (`git diff`, `git status`,
   and the conversation itself).
2. Update `docs/ARCHITECTURE.md` to reflect the current state of the
   system — not what was planned, what's actually there now. Add,
   redraw, or expand Mermaid flowchart diagrams wherever they'd clarify
   a single feature or how multiple features connect — see the
   "Diagrams are part of this document" rule in CLAUDE.md.
3. Update `docs/INTERVIEW_PREP.md` with a new section for any feature
   completed this session, following the "Interview Prep Document" rule
   in CLAUDE.md — including a verified "Further reading" link (a
   university source, a paper's official venue, or a well-known author)
   wherever one genuinely helps. Skip it rather than link something
   unverified.
4. Update `docs/pipeline-status.html`: mark newly completed steps as
   done, leave the rest pending, matching the page's existing visual
   format and style.
5. Append a new dated entry to `docs/PROGRESS.md`: what was built, what I
   struggled with, what to revisit, what's next, and a completion
   estimate — following the "Progress Tracker" rule in CLAUDE.md. Never
   rewrite past entries — this file is a history log, not a
   current-state snapshot.
6. Write any new ADRs for significant decisions made this session, in
   `docs/adr/ADR-XXX-name.md`.
7. Check whether this session surfaced a lesson likely useful beyond
   this one project — a mistake pattern that could recur elsewhere, a
   technology now used hands-on for the first time, a design pattern
   worth reusing. If so, silently append it to
   `~/.claude/global-memory/interview-prep-projects.md`, in the same
   style as its existing entries — no need to ask first or call it out
   separately in the summary. If nothing this session rises to that
   level, skip this step; not every session needs a global entry.
8. Check `README.md` — update it only if something changed that a reader
   would actually need: new setup/run steps, a status change (e.g. the
   project just became runnable), or an outdated instruction. Keep it
   minimal — don't turn it into a second architecture doc.
9. Check `git status`'s untracked-files list against `.gitignore` before
   staging anything: flag anything that shouldn't be pushed (stray env
   files, build/cache output, editor/OS junk, credentials, large data
   files) and add a pattern for it to `.gitignore` rather than staging
   it. If everything untracked is legitimately new project content,
   no `.gitignore` change is needed.
10. Stage and commit all of the above plus the session's code changes,
    then push to the remote. If no remote is configured, ask me for the
    repository URL first.
11. Confirm the commit and push actually happened by checking `git status`
    and `git log` — don't assume.
12. Give a short summary (5–10 lines) of what was updated and pushed.
