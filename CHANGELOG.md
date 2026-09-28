# Changelog

All notable changes to the Sales Memory Agent are recorded here, newest first.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- `CHANGELOG.md` and a `docs/` folder for planning and design notes.

## 2026-09-28 — Sales Memory Agent baseline

### Changed
- Hindsight is the only source of truth: the deal record, every conversation and every outcome are Hindsight
  documents; the API keeps no store of its own. Conversations can be added from the UI. (`6946978`)
- Pivoted from "Machine Never Miss" to the Sales Memory Agent: one Acme deal built from the Maven Analytics CRM
  dataset plus generated email, call and WhatsApp conversations, retained into Hindsight; profile and chat via
  `reflect` with an evidence gate on citations. (`97d8bb2`)

### Earlier (Machine Never Miss prototype, superseded)
- Agent learns from its own mistakes and writes pattern playbooks. (`e39e628`)
- Frontend moved to React + Vite + TypeScript + Tailwind. (`0303d51`)
- Near-miss memory agent MVP on Hindsight. (`0f61cf7`)
