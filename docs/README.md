# Documentation Index

## Purpose
This folder is the single source of truth for project context required for delivery and support.

## Structure
- `project/brief.md`: Product and business context
- `project/glossary.md`: Shared terms and definitions
- `project/frontend-requirements.md`: React + TypeScript frontend requirements and decisions
- `project/epics.md`: Product epics, dependencies, and delivery order
- `project/tasks.md`: Task-level backlog derived from epics with priorities
- `project/plan.md`: Phased delivery plan (created by the coordinator on first planning pass)
- `architecture/overview.md`: System architecture and pipeline-stage boundaries
- `architecture/diagrams.md`: Canonical architecture and data-flow diagrams
- `architecture/decisions.md`: Decision log (ADR-lite)
- `architecture/adr-template.md`: Template for major decisions
- `engineering/best-practices.md`: Mandatory development best practices
- `testing/strategy.md`: Test strategy and verification matrix
- `operations/github-workflow.md`: Branching, PR, and protected branch policy
- `operations/runbook.md`: Operational procedures and incident basics
- `operations/release-checklist.md`: Release readiness checks
- `operations/changelog.md`: Project release and breaking-change log
- `llm/start-here.md`: How an LLM agent should begin work
- `llm/context-map.md`: Which docs to load per task type
- `llm/task-template.md`: Prompt template for implementation tasks
- `llm/handoff-template.md`: Delivery handoff template
- `llm/docs-update-checklist.md`: Required documentation updates per change
- `features/README.md`: Feature notes index and template
- `ownership.md`: Document owners and review cadence

## Update Policy
- Update docs in the same PR/task as the change.
- Keep facts close to source; avoid duplicated text.
- Prefer short sections and explicit tables over long prose.
