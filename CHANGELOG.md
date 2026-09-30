# Changelog

## 1.0.0 — release preparation (unreleased)

- Present the framework and analyzer consistently as **Agent Level**.
- Add the `agent-level` entrypoint with default assessment, `assess`, `record`, and
  `compare`; keep existing commands and legacy report defaults.
- Rename distribution metadata from `ai-engineering-assessment` to `agent-level`.
- Add bilingual onboarding, an L0–L7 visual, and a deterministic synthetic report generator.
- Add Python 3.10–3.13 CI, installation coverage, contributor/security guidance,
  and citation metadata.
- Make existing gaps visible with optional evidence-collection experiments in English/中文.
- Add architecture and setup guides, and issue/PR templates.
- Leave all target-project ignore rules under the project's control; bootstrap
  does not create or modify `.gitignore`.
- Reject inconsistent JUnit aggregates and recognize known test executable paths.
- Isolate invalid automatic task records with explicit partial-data diagnostics.
- Stream hash-only evidence and bound the shared content cache.
- Store and discover daily records only under `agent_level/tasks/`.
- Add final-edit verification coverage and structured/opaque tool visibility without changing level gates.
- Freeze new acceptance plans, record standard provenance and append typed human review separately.
- Add stable diagnostic references, normalized failure reasons and token breakdowns by recorded role.

Existing v1 functionality includes local Claude Code/Codex analysis, L0–L4
workflow candidates, task acceptance evidence, controlled before/after comparison,
and offline English/中文 reports. Ruleset `1.0`, assessment thresholds, and protocol
version `1.1` are unchanged; provenance/review fields are backward-compatible
additions. This preparation does not create a release or license.
