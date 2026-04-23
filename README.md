# My Brain Is Full — Crew

This repository is a conversational second-brain system built around an Obsidian vault and a small crew of specialized AI workers.

Instead of managing notes, folders, reminders, and maintenance by hand, you interact through chat. The dispatcher interprets what you want, routes the request to the right skill or agent, and writes the result back into the vault structure.

This fork keeps the original project surface intact and adds a cleaned reference pack for runtime hardening under `references/runtime-hardening/`.

## What This Project Does

The system is designed for people whose life admin, ideas, deadlines, and notes do not stay neatly sorted on their own.

It helps with things like:

- capturing messy thoughts into usable notes
- searching and synthesizing vault content
- keeping inbox notes from piling up
- turning dated commitments into surfaced reminders
- maintaining operational views like current state, open loops, and daily focus
- connecting email, calendar, and vault workflows when those integrations are available

## Main Structure

The project has two main execution layers:

- **Agents** for bounded jobs such as capture, search, linking, maintenance, and communication
- **Skills** for guided multi-step flows such as onboarding, inbox triage, weekly agenda generation, and audits

The dispatcher checks skills first, then falls back to agents for simpler reactive tasks.

## What This Fork Adds

This fork includes a sanitized runtime-hardening reference pack:

- `references/runtime-hardening/scripts/`
- `references/runtime-hardening/tests/`
- `references/runtime-hardening/README.md`

That pack contains reusable guard, audit, orchestration, and regression-test patterns extracted from a private vault hardening pass, with personal details removed.

## Getting Oriented

If you want the core project, start here:

- `docs/getting-started.md`
- `docs/codex-cli.md`
- `docs/codex-migration.md`
- `references/agents-registry.md`

If you specifically want the sanitized hardening material, go straight to:

- `references/runtime-hardening/README.md`

## Notes

- This repository contains project code and reference materials, not a personal vault export.
- The added runtime-hardening pack is reference material, not a standalone productized distribution.
- If you use this on real personal data, privacy and operational safety are your responsibility.
