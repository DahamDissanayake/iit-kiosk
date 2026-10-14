# iit-kiosk

Work in this repository comes from SerenEdge. Each task or issue arrives with a
SerenEdge key (for example `PROJ-42`), and that key is used in branch names and
commit messages. This branch structure is how every change lands, not just the
first one.

## Branch structure

- `main` holds released code. Nothing is committed to it directly; `dev` is
  merged into `main` at release points.
- `dev` is the integration branch where day-to-day work happens.
- Every change gets its own short-lived branch off `dev` and is merged back
  into `dev` by pull request.

## Rules for every agent and contributor

- Work only on a branch off `dev`, named `task/<KEY>-<short-slug>`
  (for example `task/PROJ-42-add-due-dates`). When the work is a bug or issue,
  use `issue/<KEY>-<short-slug>` (for example `issue/PROJ-57-login-error`).
- Open a pull request into `dev`. Never commit straight to `main`.
- Commit messages are `<KEY>: short imperative summary`
  (for example `PROJ-42: add due dates`).
- Never add a `Co-Authored-By` trailer, a "Generated with" line or any AI or
  agent attribution to commits, pull requests, code comments or docs.
- Never commit secrets or a `.env` file.
- Do not add new frameworks or dependencies without asking.
- Keep changes small and tied to one task.
