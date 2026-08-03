# GitHub Workflow and Branch Protection

## Repository
`https://github.com/RubyFoc/diploma-maker` — public, owned by the `RubyFoc` account (same account
used for `cv-analyzer`).

## Branching Model
- `main`: protected release-ready branch.
- `feature/TASK-xx-short-name`: feature branch for one task.
- `hotfix/TASK-xx-short-name`: urgent production fixes.

## Pull Request Rules
- Direct push to `main` is forbidden once branch protection is configured.
- Every change goes through a PR with a linked `TASK-*`.
- Current repository mode: solo delivery (`0` required approving reviews).
- Team-target policy (when multiple maintainers are active): minimum 1-2 reviewers.
- Required CI checks: `docs-check`, `backend`, `frontend`.
- Squash merge by default to keep history clean.

## Review Responsibilities
- Solo mode default: self-review + required CI checks.
- Solo mode merge rule: do not wait for external PR approvals; document an architectural
  self-review in the PR for architecture-affecting changes.

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
