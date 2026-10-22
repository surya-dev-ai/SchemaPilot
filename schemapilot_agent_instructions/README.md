# SchemaPilot — AI-Powered Database Migration Safety Agent

This folder contains project instructions for AI coding assistants and a build plan for the SchemaPilot final-year project.

## Included
- `CLAUDE.md` — primary instructions for Claude Code.
- `instructions.md` — complete product, architecture, requirements, safety rules, and acceptance criteria.
- `.github/copilot-instructions.md` — repository-wide GitHub Copilot guidance.
- `.cursor/rules/schemapilot.mdc` — Cursor project rule.
- `IMPLEMENTATION_PLAN.md` — staged implementation plan and definition of done.
- `SECURITY.md` — security and operational guardrails.

## How to use
1. Copy these files into the root of your repository, preserving the folder paths.
2. Open the repository in Claude Code, Cursor, or VS Code with Copilot.
3. Ask the assistant to read `CLAUDE.md` (Claude Code), `instructions.md`, and `IMPLEMENTATION_PLAN.md` before coding.
4. Build in small, reviewable slices. Do not ask the assistant to generate the whole application in one pass.
5. Keep `IMPLEMENTATION_PLAN.md` updated as tasks are completed.

## Project principle
**AI proposes. The system verifies. The user approves.**

The project must never silently apply an AI-generated migration to a real database.
