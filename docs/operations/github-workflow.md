# GitHub Workflow and Branch Protection

## Repository
`https://github.com/RubyFoc/diploma-maker` — public, owned by the `RubyFoc` account (same account
used for `cv-analyzer`).

## Branching Model
- `main`: protected release-ready branch.
- `feature/TASK-xx-short-name`: feature branch for one task.
- `hotfix/TASK-xx-short-name`: urgent production fixes.

## Pull Request Rules
- **Current mode (2026-08-04, user decision): direct push to `main` is allowed.** No PR is
  required, no branch protection is configured. This is intentional — kept simple while the
  project is a solo build with no other collaborators to protect against.
- CI (`docs-check`, `backend`, `frontend`) still runs on every push to `main` and should be green;
  it's just not a hard merge gate yet.
- Team-target policy (revisit if a second maintainer joins): require PRs, branch protection with
  required status checks, and 1-2 reviewers — this section should be updated then, not before.

## Review Responsibilities
- Solo mode: self-review is sufficient; no PR/approval step is enforced.

## Commit and PR Hygiene
- Commit scope: one concern per commit.
- Commit message style: `type(scope): summary`.
- PR description must include verification commands and risks (see
  `.github/PULL_REQUEST_TEMPLATE.md`).

## Post-Merge Closeout
- Review GitHub issues linked to the merged task/PR; close only the ones actually resolved.
- Sync `docs/project/tasks.md` if the merge changes backlog status.
- Delete branches that are no longer needed, locally and on GitHub.

## GitHub CLI Operations (`gh`)
- This repo's origin remote is configured with a `RubyFoc`-scoped personal access token
  (`.git/config`, not committed). Do not print the token in chat, logs, or commit messages.
- Always check auth state before PR automation: `gh auth status` reports the environment's
  default account; use `GH_TOKEN=<token> gh <command>` to act as `RubyFoc` for this repo without
  switching the global default account.
- If a push/PR command fails with "Repository not found", verify which account's token is active
  before assuming the repo is missing.
