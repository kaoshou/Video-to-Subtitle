# MCP project players implementation plan

**Goal:** MCP discovers OpenCam/EverCam media and exports the matching multilingual player with chapters.

**Architecture:** Add `mcp_projects.py` for bounded project detection, resource snapshots and native player building. Keep MCP's existing private workspace, authorization checkpoints and exclusive new-directory publication. Source projects remain unchanged. OpenCam schema-v1 exports are self-contained index/data/media; EverCam uses the bundled player and original config with a normalized local media URL.

**Scope approved in conversation:** Detect projects, retain chapters and existing subtitle languages, select matching player automatically; expose optional `player_type` override. No change to translation/timing or desktop behavior.

## Tasks

- [x] Add integration tests for discovery, automatic/explicit player selection, chapter and multilingual preservation, missing subtitles, collisions, source mutation and unsafe project links.
- [x] Implement pinned-directory detection and bounded resource fingerprints; return `project_type` and project details from `list_media`. Asset IDs include project fingerprints so changed project metadata receives a fresh identity.
- [x] Build native OpenCam or modern EverCam packages privately, then reuse exclusive publication; validate project resources again before publication. Explicit incompatible type fails rather than silently exporting MP4.
- [x] Update MCP schema, tool instructions, documentation and executable smoke coverage.
- [x] Run project tests, existing MCP and player tests, and review authorization, cancellation, source preservation and packaging imports.

## Review focus

Files named MP4 that are actually directories; unrelated MP4 next to OpenCam; invalid OpenCam data; linked or replaced project resources; projects with no or multiple existing languages; incomplete requested translations; output collisions; type changes between listing and export.

## Verification record

Full local Python suite: 568 tests, 103 environment/platform skips, no failures. Player tests: 43 passed. Real source-mode STDIO/broker smoke passed for MP4, OpenCam and EverCam. Nine project integration tests cover resource mutation, linked/malformed data, native language merging, blank subtitles, forced type mismatch, collisions and large self-contained index files. Frozen executable smoke now includes both project types, ready for the next Windows build.

Self-review: existing policy checks and exclusive publication remain shared. Source projects are read through pinned directories; resource identities are checked at discovery, build and final publication. OpenCam native standard exports contain self-contained index/data/media files; arbitrary external companion assets are outside the supported schema-v1 export structure. EverCam config is carried to the browser, never evaluated by the MCP service. No remote push or release in this implementation task.
