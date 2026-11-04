# MCP Workflow Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local transcription and multilingual player jobs understandable, resumable and quality-aware without adding repetitive confirmations.

**Architecture:** Extend existing bounded MCP contracts, Service records and desktop cards. Keep inference subprocess events primitive and bounded; add pure summary/quality helpers rather than another scheduler.

**Tech Stack:** Python, unittest, CustomTkinter, existing MCP SDK; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-05-mcp-workflow-design.md`

## Global Constraints

- 設定明確就直接執行，缺漏、模型不可用或需要變更方案時才詢問，不增加每次必答的確認視窗。
- Preserve existing tool input compatibility, path/identity authorization, cancellation and fixed private output contracts.
- Never download/delete models, overwrite originals, modify source timing, or silently change the requested model.
- Unknown progress is null; interrupted inference restarts explicitly, not from a fictitious decoding checkpoint.
- Bound all list responses and warning details. Legacy records remain readable.
- No push, version bump, packaging or release in this plan.

## Review Focus

- Model ready at preview but missing at start: execute-time validation must still reject safely (Task 1).
- Malformed/repeated child progress: reject invalid events and throttle persistence, preserve cancellation (Task 2).
- Source edited or access revoked after completion: recovery must not expose stale/unauthorized work (Task 3).
- Short proper nouns or same-language translation: avoid claiming identical text proves mistranslation (Task 4).
- Legacy jobs lack timing/review fields: cards render without fabricating historical values (Task 5).

### Task 1: Read-only transcription preview

**Files:** `mcp_contracts.py`, `mcp_service.py`, `tests/test_mcp_service.py`, `docs/MCP.zh-TW.md`.

**Interfaces:** Add `preview_transcription(asset_id, settings={}) -> {settings, model_status, can_start, blockers, source_name, output_parent, project_type}` using existing settings resolution and authorization. Never return cache paths. Add the resolved execution plan to accepted transcription responses. Preserve old request shapes.

- [ ] Write tests for explicit/default model, missing cache, no download/load, policy revocation and preview/start race; run and observe failure.
- [ ] Implement preview using shared resolution and existing offline cache checks; keep start-time validation authoritative.
- [ ] Update AI instructions: disclose resolved plan, ask only for missing choices or changed strategy, never silently downgrade.
- [ ] Run `PYTHONPATH=tests python -m unittest test_mcp_service` and inspect the diff before a scoped commit.

### Task 2: Real progress and lifecycle timing

**Files:** `mcp_service.py`, `mcp_jobs.py`, `mcp_dialog.py`, `tests/test_mcp_service.py`, `tests/test_mcp_jobs.py`.

**Interfaces:** Job fields `progress: {stage, fraction: float|null}`, `started_at`, `finished_at`, `elapsed_seconds`. Engine callbacks emit bounded primitive progress/stage events; final report stays distinct from events. Export byte progress uses existing copy callbacks.

- [ ] Write tests for callback progress, invalid event fractions, duplicate events, cancellation, queued versus running time and final-message ordering; demonstrate failure.
- [ ] Implement validated/coalesced subprocess events, throttled job persistence, phase-aware progress and terminal timing. Do not expose subtitle text through progress events.
- [ ] Render meaningful stage/progress and elapsed values without estimating unsupported completion times.
- [ ] Run service and job-card tests; run targeted desktop tests with `VTS_RUN_GUI_TESTS=1`; review and commit scoped changes.

### Task 3: Discover recoverable work by media

**Files:** `mcp_contracts.py`, `mcp_service.py`, `tests/test_mcp_service.py`, `docs/MCP.zh-TW.md`.

**Interfaces:** Add `list_work(asset_id, cursor=0, limit=20)` returning bounded authorized source/job/draft references, language, revision validity, completed/missing batch counts and next action. Reuse `list_translation_drafts` for actual batch IDs.

- [ ] Write tests for finding completed transcription without old IDs, partially translated languages, pagination, source version changes and access revocation; observe failure.
- [ ] Implement media-scoped discovery, no whole-filesystem scan, and explicit retry guidance for interrupted inference. Keep completed batches immutable under identical request replay.
- [ ] Document a new-dialog recovery prompt and distinction between translation resume and inference restart.
- [ ] Run service/idempotency/authorization tests; review and commit scoped changes.

### Task 4: Translation quality and glossary checks

**Files:** `mcp_translation.py`, `mcp_contracts.py`, `mcp_service.py`, `tests/test_mcp_translation.py`, `tests/test_mcp_service.py`.

**Interfaces:** Add pure `quality_report(cues, translations, source_language, target_language, glossary_terms) -> {review_count, reason_counts, items, truncated}`. Bounded items reference cue IDs and reason codes. Optional structured `glossary_terms` map supplements legacy glossary text. Persist report with finalized tracks and expose bounded review details through a paginated tool.

- [ ] Write tests for missing/empty cues remaining hard errors, unchanged timestamps, reading-speed/length warnings, source-target language equality, non-Latin text, deterministic glossary mismatches and warning truncation; observe failure.
- [ ] Implement conservative advisory rules with documented thresholds; no semantic correctness claims or automatic text replacement. Reports cover all cues even when detail items are bounded.
- [ ] Preserve old glossary/string-only submissions and draft replay behavior; verify persisted review summaries survive service restart.
- [ ] Run translation/service tests, review and commit scoped changes.

### Task 5: Unified outcome summaries and UI

**Files:** `mcp_jobs.py`, `mcp_dialog.py`, `mcp_service.py`, `tests/test_mcp_jobs.py`, `tests/test_mcp_dialog.py`, `docs/MCP.zh-TW.md`.

**Interfaces:** Extend result summaries with actual transcription metadata, duration, output language(s), cue count, aggregated review reasons and authorized output locations. Additive fields only; imported subtitles never claim an inference model.

- [ ] Write tests for old jobs, imported subtitles, multilingual exports, failed/cancelled jobs, review counts, detail expansion and result opening; observe failure.
- [ ] Wire source/track review and timing metadata to export results, AI completion instructions and concise desktop cards. Retain technical IDs under details.
- [ ] Update manual with actual field examples, thresholds, limitations and recovery workflow.
- [ ] Run full Python suite, player tests and native GUI tests; inspect `git diff --check`. Record actual results and limitations before declaring completion.
