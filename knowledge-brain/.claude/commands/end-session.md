---
description: Update project docs and push all changes to close out a session
---

Close out the current working session on this project:

1. Review everything built or changed this session (`git diff`, `git status`,
   and the conversation itself).
2. Update `docs/INTERVIEW_PREP.md` with a new section for any feature
   completed this session, following the "Interview Prep Document" rule
   in CLAUDE.md — the high-level workflow only (what it does in one
   sentence, the start-to-finish flow as I'd say it out loud, the one or
   two design choices an interviewer would push on), plus that feature's
   own Mermaid flowchart. No file names, no function names, no
   implementation detail. Add a verified "Further reading" link (a
   university source, a paper's official venue, or a well-known author)
   wherever one genuinely helps; skip it rather than link something
   unverified. If this session's work changed how an earlier feature
   behaves, fix that earlier section in place too — I must never
   rehearse an answer describing a design we've since changed.
3. Update `docs/pipeline-status.html`: mark newly completed steps as
   done, leave the rest pending, matching the page's existing visual
   format and style. Minimal change only — no redesign, no prose.
4. Update `docs/PROGRESS.md` as a current-state snapshot, per the
   "Progress Tracker" rule in CLAUDE.md — Done lines, Pending lines, and
   the time-to-finish estimate ("at 3–4 hours/day, roughly X working
   days left"). A feature finished this session moves from Pending to
   Done; re-state the estimate; leave lines that are still correct
   exactly as they are. This file is not a session diary — no struggle
   log, no lessons learned, no dated narrative entries.
5. Do not touch `docs/ARCHITECTURE.md` or anything in `docs/adr/`. Both
   are frozen history, per CLAUDE.md: no new ADRs, no edits to existing
   ones, no architecture updates — not even to correct a section this
   session made stale.
6. Check whether this session surfaced a lesson likely useful beyond
   this one project — a mistake pattern that could recur elsewhere, a
   technology now used hands-on for the first time, a design pattern
   worth reusing. If so, silently append it to
   `~/.claude/global-memory/interview-prep-projects.md`, in the same
   style as its existing entries — no need to ask first or call it out
   separately in the summary. If nothing this session rises to that
   level, skip this step; not every session needs a global entry.
7. Check `README.md` — update it only if something changed that a reader
   would actually need: new setup/run steps, a status change (e.g. the
   project just became runnable), or an outdated instruction. Keep it
   minimal — don't turn it into a second architecture doc.
8. Check `git status`'s untracked-files list against `.gitignore` before
   staging anything: flag anything that shouldn't be pushed (stray env
   files, build/cache output, editor/OS junk, credentials, large data
   files) and add a pattern for it to `.gitignore` rather than staging
   it. If everything untracked is legitimately new project content,
   no `.gitignore` change is needed.
9. Stage and commit all of the above plus the session's code changes,
   then push to the remote. If no remote is configured, ask me for the
   repository URL first.
10. Confirm the commit and push actually happened by checking `git status`
    and `git log` — don't assume.
11. Give a short summary (5–10 lines) of what was updated and pushed.
