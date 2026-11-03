# Optional local MCP implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved optional local MCP workflow: authorized media → transcription → reliable multilingual text backfill → new web player, with safe client setup and no changes to existing default behavior.

**Architecture:** Thin STDIO entry proxies to one private per-user background broker. Broker owns persistent jobs and translation drafts; all high-load GUI/MCP work shares a cross-process lock. Client setup and GUI policy are local administrative operations, never AI tools.

**Tech Stack:** Python 3.11+, existing safe_files/PyAV/faster-whisper/MLX; official Python MCP SDK `>=1.30,<2`, optional/lazy import; TOML-preserving client configuration adapter; CustomTkinter; platform-private IPC and PyInstaller. Use `/private/tmp/vts-mcp-validation-env/bin/python` for all test commands below.

**Spec:** `docs/superpowers/specs/2026-11-04-optional-mcp-design.md` (user explicitly requested implementation on 2026-11-04).

## Global Constraints

- Default disabled; opening the ordinary app does not create an MCP runtime, scan clients, start a service, load a model or expose a TCP listener.
- Windows x64/macOS arm64 packaging; preserve the three current Release assets; no version bump, push, Release, real AI config change, or cloud media upload in this task.
- Only user-approved roots; no shell, arbitrary file read/write, arbitrary URLs, deleting models, automatic model downloads, or weakening client approvals.
- Use existing safe filesystem primitives; reject traversal, symlinks/reparse points and malformed inputs. Private runtime data and backup contents never enter tool results/logs.
- Preserve original subtitle timing. Translation accepts cue ID/text only; original source revision is immutable; batches at most 50 cues and 8,000 source Unicode characters, at most 32 language tracks.
- Independent background lifetime; one high-load transcription across GUI/MCP; no forced kill of native inference; 300-second idle exit when no jobs or clients.
- Client detected/configured/handshake verified/actual connection are distinct. Unknown or untested client formats are manual-only. Include Cursor, VS Code/GitHub Copilot, Windsurf and OpenCode in discovery/manual routes as well as Codex, Claude and Gemini products; each has its own adapter and truthful capability label.
- Model ownership includes memory residency, not just running inference: use a short-lived isolated inference process for background jobs, and for GUI batches while MCP is enabled. Reuse the model within a GUI batch, then let that child exit before releasing the shared lock. No model downloads/deletion; trade a reload between jobs for guaranteed CPU/CUDA/MLX memory release. Enabling MCP after an in-process GUI engine was loaded requires an explicit application restart before activation, rather than guessing at third-party global caches.
- Implementers may only mutate task-owned files. No subagents from workers. TDD: write and run failing tests, implement, focused GREEN, then full suite before local commit. All tests use temporary synthetic inputs, not user settings/media/models.

## Review Focus

- Replayed write requests and cross-client concurrency must not duplicate jobs, overwrite translations, or load two GPU models.
- Source/root replacement or revocation after enqueue must prevent further access/publication, not merely pass an earlier path check.
- Turning off MCP must affect existing sessions; administrative settings are not exposed as AI-callable tools.
- Frozen Windows GUI executables have no STDIO; the actual packaged MCP entry must handshake without Python/Node installed and without a Tk/console window.
- Config backups/removal must not expose secrets or restore an entire old config over unrelated later edits; unsupported client versions cannot get a false-success label.

---

### Task 1: Private policy, durable records and process locking

**Files:** Create `mcp_state.py`, `tests/test_mcp_state.py`.

**Interfaces:**
- `MCPError(code: str, message: str)` with `.code`.
- `default_state_dir() -> Path` (no I/O); `State(path: Path | None = None)` (no I/O until explicit writes).
- `State.policy() -> dict`: missing policy is `{enabled: False, roots: [], generation: 0}`. Roots are `{id, path, label}`; only local admin calls `configure(enabled: bool, roots: list[Path], **options) -> dict`. Options hold model/device/cache preferences, stop mode, backend command, never host API secrets.
- `State.require_enabled(*, admitted_generation=None) -> dict`; `State.directory(root_id, relative='', *, admitted_generation=None)` yields a pinned `SafeDirectory`; `State.file(root_id, relative, *, admitted_generation=None)` yields a pinned readable regular stream. All authorization rechecks current policy and walks from the trusted root without following descendants. Internal admitted generation permits only previously accepted work while disabled in finish mode and roots unchanged; revocation/cancel clears drain permission. It is never accepted as a tool argument.
- `State.get(kind, id) -> dict`, `put(kind, id, data)`, `records(kind) -> list[dict]` for bounded, opaque-ID JSON records in private storage, safe atomic writes and per-record mutation locking as needed. Valid kind namespaces are fixed, IDs validated; no arbitrary file names from tools.
- `ProcessLock(directory: Path, name='inference')` with `acquire(blocking=False, cancelled=None) -> bool`, `release()`, context manager; OS-backed fcntl/msvcrt lock, no stale PID-only locks. Private storage creates owner-only POSIX permissions / Windows user ACL. No arbitrary owner changes.

- [ ] RED: absent policy does not create paths; configure persists approved root IDs; disabled/revoked/traversal/absolute/ADS/symlink/reparse access rejects; pinned reads work; invalid record IDs reject; same-name process lock cannot be held by two subprocesses, releases after process death; roots retain stable IDs.
- [ ] Run `/private/tmp/vts-mcp-validation-env/bin/python -m unittest discover -s tests -p test_mcp_state.py -v`; expected missing module/API failure before code.
- [ ] Implement the interfaces, including fail-closed malformed policy and safe bounded records. Add no GUI, SDK, cloud or client imports.
- [ ] GREEN focused tests, then `python -m unittest discover -s tests`; expected zero failures (platform skips explicit).
- [ ] Commit task-owned files and report RED/GREEN commands/results.

### Task 2: Translation contracts, read tools, persistent transcription/export jobs

**Files:** Create `mcp_service.py`, `mcp_translation.py`, `tests/test_mcp_service.py`, `tests/test_mcp_translation.py`.

**Interfaces:**
- Consumes State, MCPError, ProcessLock above.
- `Service(state: State, *, transcribe_factory=None)`; `call(name: str, arguments: dict) -> dict`; `.close()` cancels/joins owned threads without changing policy; `.busy` is true for accepted nonterminal work. Broker task will own one Service instance.
- Tool names match spec: `get_status`, `list_media`, `start_transcription`, `get_job`, `cancel_job`, `import_subtitle`, `read_transcript`, `prepare_translation`, `get_translation_batch`, `submit_translation_batch`, `finalize_translation`, `export_player`. Separate immutable `TOOL_SCHEMAS` mapping with JSON input schemas for protocol task.
- Opaque IDs only; `list_media` returns root-relative asset identities, excludes unsupported inputs; imports snapshot original cues/hash. Exposed settings are allowlisted, do not mutate GUI config. Do not import Whisper until an actual transcription job.
- Model readiness uses existing `inspect_model_cache`/`check_model_downloaded`; missing/access errors do not prompt/download/clear. Reuse existing transcriber API callbacks and core safety. Copy authorized media with pinned handles into private job workspace before decoding; use that snapshot for model runs and source validation. Stream copy, not whole-video bytes.
- Real inference runs in a short-lived multiprocessing child (module-level target in mcp_service.py), with structured bounded status/results, cooperative cancellation and no forced native kill. Child exits before the shared lock is released, so model/Metal global caches cannot overlap with GUI. The injected test factory can execute inline as an explicit test seam; never serialize an AI-provided function/command. The child rechecks model readiness and local-only behavior immediately before loading.
- Persistent idempotency on `(tool, request_id)` plus canonical argument digest; identical returns original result/job, conflicting rejects. Broker serializes writes; record-level guard also protects direct test/admin callers.
- `start_transcription`/`export_player` return job ID immediately; one worker queue owns heavy calls and shared inference lock; cancellation/revocation rechecked before publication. Interrupted old jobs are marked, not silently re-executed. Do not use global GUI flags.
- Translation helper functions may be module-private; public behavior via Service. Authoritative timing only server-side; complete batch validation before writing, max 50 cues/8,000 chars, complete finalize emits `media.<lang>.srt` using original timing, source version rejects stale source. Language defaults/metadata comply with existing canonical_language.
- Export calls existing export_package with fresh exclusive name and explicit requested complete track IDs. Source video target parent must remain authorized; no original overwrite, no browser opening. Source/output path is allowed in successful export result; internal settings/private paths are not.

- [ ] RED: real synthetic MP4/SRT import → two-language batches → finalize → real player export; nonzero timeline preserved exactly; missing/duplicate/foreign cue IDs fail atomically; stale source/role revocation block; repeated request IDs do not duplicate output; incomplete requested languages block; queue/cancel/restart states correct; off rejects existing Service calls.
- [ ] Run `python -m unittest discover -s tests -p 'test_mcp_*'`; expected missing Service/translation functionality failure.
- [ ] Implement with bounded reads and persisted batch state. Use injected transcription factory only to replace costly inference in tests, not storage, parsing, lock or publication.
- [ ] GREEN focused tests then full Python suite; commit task-owned files and report.

### Task 3: STDIO protocol, private IPC broker and headless bootstrap

**Files:** Create `mcp_transport.py`, `mcp_entry.py`, `app_entry.py`, `tests/test_mcp_transport.py`; modify `pyproject.toml` only for required optional MCP dependencies.

**Interfaces:**
- Consumes State, Service, TOOL_SCHEMAS; `mcp_entry.main(argv=None) -> int` handles `--state-dir` (local explicit launcher argument, not tool parameter), `--broker`, `--self-test`; STDIO default serves tools through broker.
- `app_entry.py` becomes eventual packaging entry: call `multiprocessing.freeze_support()` first; `--mcp-broker` dispatches without importing Tk; ordinary invocation uses existing GUI module's main behavior. Preserve all existing `--from-installer`/smoke modes.
- Local daemon IPC: AF_UNIX under owner-private runtime dir; Windows AF_PIPE named pipe plus current-user ACL/authentication, never pickle deserialization of client data, bounded JSON `send_bytes`/`recv_bytes`. Add per-user runtime secret authentication; no TCP fallback. Validate data/JSON lengths/schema before dispatch. No secret in client config/tool output.
- One broker via OS process lock; thin bridge spawns broker detached using configured validated backend argv with no shell, bounded readiness wait; paths absolute, no current-working-directory dependency. Multi-client bridge processes do not create independent Service/model pools. Idle timer 300 sec and safe shutdown.
- Use official MCP SDK in isolated optional imports if available; pin supported version range and negotiate documented protocol. STDOUT is protocol-only, progress/prints stderr/private logging. Provide initialize, tools/list, tools/call, ping; preserve structured tool errors, job progress poll, no administrative tools. Full protocol test uses a separate real client subprocess, not string containment.
- `--self-test` uses current policy's read-only get_status/handshake; never grants roots or enables policy. GUI Task 5 consumes `probe_connection(state_path, command) -> dict` helper or `--self-test` structured output.

- [ ] RED: subprocess handshake/list/call, bad JSON/oversize frames, off state, client EOF, second bridge shares broker, restart/no Tk import, protocol output free of debug; cancellation over independent client; IPC wrong auth rejected.
- [ ] Verify RED, implement, GREEN with official SDK client where feasible, then full suite. Only install dependencies into test env, never user AI tools or system Python.
- [ ] Commit task-owned files and report.

### Task 4: Client discovery, safe configuration and manual MCPB export

**Files:** Create `mcp_clients.py`, `tests/test_mcp_clients.py`; modify `pyproject.toml` if TOML-preserving adapter dependency required.

**Interfaces:**
- `discover_clients(*, home=None, environ=None, system=None) -> list[dict]` metadata-only; records include client ID, name, detected evidence, config target, support/manual reason. Fake home/env in tests; never inspect actual user config to validate implementation.
- `connection_entry(command: list[str], client_id: str) -> dict|str` uses absolute executable plus argv, no shell.
- `preview_connection(client_id, config_path, command, *, state_dir) -> dict` validates known schema, private backup plan, records original hash, owned entry before/after; output sanitized entry diff only, not whole file/secrets.
- `apply_connection(preview, *, state_dir) -> dict` compares original hash, backs up privately, writes preserving all unrelated config/comments/ordering as supported; fixed key video-to-subtitle; refuses conflicting unknown entry. `remove_connection(client_id, config_path, *, state_dir)` only removes unchanged managed entry, never full-file rollback. JSON maximum 1 MiB; unsupported version read-only/manual export.
- Codex TOML, Claude Code JSON scoped entry, Gemini CLI JSON and Antigravity JSON adapters separate; version/evidence ambiguity remains manual. Claude Desktop generates `.mcpb` manifest/binary package to explicitly user-selected new output without modifying Claude's settings. Need not silently install package or claim real client validation.
- Include Cursor, VS Code / GitHub Copilot, Windsurf and OpenCode rows with their own official schemas. VS Code uses `servers`, Copilot portable configuration differs, OpenCode uses `mcp` and command arrays. Preserve JSONC/comments or offer manual-only; do not treat a detected executable or schema fixture as a live-client verification. Research current official configuration paths before implementing adapters; unknown/untested versions are manual-only.
- `manual_configuration(client_id, command) -> str`; `export_mcpb(destination, command, ...)` API can be settled and reported for GUI consumption; bundled binary path cannot depend on source-only Python for packaged use.

- [ ] RED: fixtures with existing servers/secrets/comments survive add/remove; repeat add unchanged; unknown same-name conflict; edit-after-preview refuses; remove after unrelated edit preserves it; malformed/oversize/read-only/link config refuses; discovery no config content mutation; unsupported versions manual-only; schema-valid MCPB zip without copying arbitrary external binaries.
- [ ] Verify RED; implement; focused GREEN and full suite; commit task-owned files and report API to controller.

### Task 5: GUI administration and shared inference protection

**Files:** Create `mcp_dialog.py`, `mcp_inference.py`, `tests/test_mcp_gui.py`, `tests/test_mcp_inference.py`; modify `SubtitleTranscriber.py`, `mcp_state.py` only if integrating shared lock requires a documented compatible helper.

**Interfaces:**
- `MCPSettingsDialog(parent, *, state=None)` with top, master switch, roots, selected client rows, configure/test/manual/remove actions, job monitor; use State/client/transport APIs, no tool exposure of admin actions.
- Compact AI 工具連接 button in existing controls, no global startup scan or MCP service. While ordinary GUI is processing/downloading, new enable/permission change deferred/refused with inline reason; existing MCP job lock conflicts shown before loading GUI model.
- GUI transcription always participates in ProcessLock at model load through full batch; lock release in finally, after owned inference child exits. While MCP enabled use mcp_inference.py process proxy matching existing constructor/load_model/run callbacks and attribute contracts; one child per GUI batch preserves reuse within that batch. MCP-off path stays existing direct engine. If a direct engine already existed, enabling MCP requests a normal application restart (no silent enable, no model-cache clearing). Preserve existing test setup process_batch and cancellation. Stop modes: deny new tool reads/writes immediately; choose finish accepted jobs or cancel, never force kill CTranslate2/Metal. Existing sessions cannot read through cached enable state.
- Discovery/network/handshake/long jobs off Tk thread with queue + after; only UI thread updates. No modal grab traps; long paths wrap, buttons keyboard reachable, dark/light themes preserved. Actual client connected vs self-test labels distinct; no false verification.
- UI configure asks explicit user confirmation including folder scope and client, never auto apply on open/toggle/detect. Tests patch actual client paths and OS account state; no real host config writes.

- [ ] RED GUI: opening default leaves policy/files untouched; root add + enable persists only explicit action; manual tool rows work, owned config setup requires confirmation, worker queue doesn't block Tk, disable cancels/finish behavior, native lock prevents concurrent GUI/MCP, close main GUI doesn't terminate accepted MCP job, all buttons visible with long Chinese paths.
- [ ] Verify RED with `VTS_RUN_GUI_TESTS=1`; implement; focused GREEN then full native Python suite; commit task-owned files and report.

### Task 6: Frozen packaging, synthetic smoke, documentation and final integration

**Files:** Create `MCPLauncher.spec`, `scripts/smoke_mcp.py`, `tests/test_mcp_packaging.py`, `docs/MCP.zh-TW.md`; modify `VideoToSubtitle.spec`, `.github/workflows/python-app.yml`, `.github/workflows/security-regression.yml`, `packaging/windows/VideoToSubtitle.iss`, `README.md`, `docs/USER_GUIDE.zh-TW.md`, existing packaging smoke as needed.

**Interfaces:**
- GUI packaging entry app_entry.py; small console STDIO launcher separately bundled with only required runtime. Embed required launcher payload in portable/app/installer; no two complete copies of Whisper dependencies; no temporary extraction path in client config. Private runtime payload activated only on explicit enable; install/update/uninstall policy invalidation is explicit and preserves models/results.
- Add packaged `--test-mcp`/launcher self-test entry as needed; existing traditional Chinese, MLX, web export, local-page and installer smoke still pass. Script invokes actual frozen launcher with no system Python/Node on PATH, synthetic temp policy/roots and JSON-RPC handshake/import/translation/player flow; no user config/model writes. Needs cached model only for actual inference tests; no fabricated hardware benchmark.
- Add separate optional MCP dependencies to build/test commands; no SDK import on ordinary GUI start. Unsupported client actual tests remain documented manual gate, not labeled passed because fixture smoke works.
- Document enable/disable, supported verified vs manual clients, privacy and AI translation cost/account limits, no API key requirement, media permission boundary, interrupted translation retry, CPU/CUDA/MLX, uninstall/repair and keyboard usage. Main guide links dedicated MCP guide; release text/version untouched.

- [ ] RED packaging smoke entry test: real source STDIO smoke creates complete two-language output, no Tk startup; off rejects; launcher stdout only protocol. Missing launcher payload reports actionable manual route, not successful configuration.
- [ ] Implement, run focused GREEN then full Python/native GUI + player/site tests/site build and locally feasible frozen smoke. Windows-only and live-client gates explicitly recorded if unavailable; do not push Actions without user authorization.
- [ ] Review entire branch via fresh reviewer on most capable model, one fix pass per workflow; record exact evidence and any unverified native/client gates. Keep disabled by default until platform criteria met.
- [ ] Commit, preserve worktree/branch, hand back local result without pushing/releasing or modifying any real AI client config.
