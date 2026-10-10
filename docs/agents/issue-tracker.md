# Issue tracker: GitHub

Issues and specs for this repo live in GitHub Issues for `triuk/Rychvald-zpravodaje-OCR`. Use the `gh` CLI from this repository for tracker operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body-file <path>`. Write multiline bodies to a temporary file with actual newlines before submitting them.
- **Read an issue**: `gh issue view <number> --json number,title,body,labels,comments`; also use `gh issue view <number> --comments` when reading the discussion.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body-file <path>`.
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`. Use the mapping in `docs/agents/triage-labels.md`.
- **Close**: `gh issue close <number>`. If a closing explanation is needed, submit it as a comment first.

`gh` infers the repository from the Git remote when run inside this clone. Use `--repo triuk/Rychvald-zpravodaje-OCR` when working outside it.

## Pull requests as a triage surface

**PRs as a request surface: no.** Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.

When enabled, use the equivalent `gh pr` operations to read, comment, label and close PRs. For external PRs, retain authors whose `authorAssociation` is `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR` or `NONE`.

GitHub shares one number space across issues and PRs. Resolve an ambiguous reference such as `#42` with `gh pr view 42`, falling back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments` and fetch its labels using the JSON form above.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: an issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body.
- **Child ticket**: link it to the map as a GitHub sub-issue using `gh api`. Where sub-issues are unavailable, add it to a task list in the map body and put `Part of #<map>` at the top of the child body. Use labels `wayfinder:<type>` (`research`, `prototype`, `grilling`, `task`).
- **Blocking**: use native GitHub issue dependencies where available. Otherwise put `Blocked by: #<n>, #<n>` at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children, exclude tickets with an open blocker or an assignee, then select the first remaining ticket in map order.
- **Claim**: `gh issue edit <number> --add-assignee @me`.
- **Resolve**: comment with the result, close the ticket, then append a short summary and link to the map's Decisions-so-far.
