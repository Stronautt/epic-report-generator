# Custom Jira Issue-Type Hierarchy and Report Refinements

## Overview

Today the app hard-codes a 2-tier child hierarchy: an Epic, its direct children (via the `parent` field / `epic_link_field`), and their sub-tasks. Real Jira instances are richer — teams model depth like `Capability —blocks→ Feature —parent→ Story —blocks→ Task —parent→ Sub-task`, mixing the native `parent` relationship with issue **links**. The report, however, must keep its fixed **3 display tiers** (Epic / Story / Sub-task).

This work lets each report **profile** define a custom **issue-type hierarchy chain** (an ordered list of issue types, each edge either `parent` or one-or-more link types, collapsed into the 3 tiers), auto-seeded from Jira and edited in a drag-driven constructor. It folds in agreed refinements: auto-detected types + a Refresh button; per-type show/estimate toggles (replacing four global flags) with down-chain cascade; an Exclude area to park irrelevant types; Jira issue-type icons across the report and UI; epic autocomplete by key + summary; label resolution that respects the chain's Epic-tier types; and a standardized user guide. Everything is **additive by default**: a profile with no saved chain auto-derives `Epic→Story→Sub-task` (all `parent`) and migrates the four old booleans so existing reports render byte-for-byte identical.

## Context

- Impacted components: `core/data_models.py`, `core/jira_client.py`, `core/metrics.py`, `core/report_view_model.py`, `core/typst_renderer.py`, `core/pdf_generator.py`, `resources/typst/` templates, `ui/widgets.py`, `ui/config_panel.py`, `ui/preview_panel.py`, `services/config_manager.py`, `resources/user-guide.md`.
- Verified live against the user's `globallogic-velocity` instance (read-only): scoped API token works only via the cloud API base (`self._jira` is already connected there); `hierarchyLevel` maps cleanly to the 3 tiers; link traversal must read the `issuelinks` field and batch-fetch targets by key (do NOT use JQL `linkedIssues()`); issue-type icons fetch as `image/svg+xml` from each type's `iconUrl`; the `issue/picker` endpoint matches both key and summary.
- Reuse-first: lean on existing widgets/utilities rather than new abstractions (see Technical Details). Keep the proven default fetch path untouched; isolate all new behavior behind a custom-chain guard.
- Adopted from approved design plan `~/.claude/plans/velvety-wondering-kazoo.md` (this session).

## Development Approach

- Testing approach: regular (pytest already in the repo; add unit tests per code-changing task).
- Complete each task fully before moving to the next.
- Default chain must reproduce today's output exactly; verify after every layer.
- Update this plan if scope changes during implementation.

## Testing Strategy

- Unit tests required for every code-changing Task (data model, fetch, metrics, view-model, migration).
- Run the project test suite after each Task before proceeding.
- Manual + live read-only verification reserved for the final acceptance Task.

## Progress Tracking

- Mark completed items with `[x]` immediately when done.
- Update the plan if implementation deviates from the original scope.

## Technical Details

- **Hierarchy model.** New `HierarchyNode` dataclass: `issue_type_id`, `issue_type` (name), `edge` (`"parent"`|`"link"`, how this node attaches to the node above; first node's edge ignored), `link_types: list[str]` (names, multiple allowed, matched in either direction), `display_tier` (0/1/2), `show: bool`, `in_estimate: bool`. `ReportConfig.issue_hierarchy: list[HierarchyNode] = []` (`[]` = derive default). Excluded types are simply not in the list (pool = complement against cached instance types; not persisted). `JiraIssue` gains `hierarchy_parent_key`, `display_tier`, `issue_type_id`, plus cascade-resolved `show`/`in_estimate`.
- **Epic-tier types.** Helper `epic_tier_type_names(chain) -> list[str]` (defaults to `["Epic"]` when chain empty) — the single source for the label JQL, label validation, and epic autocomplete scope.
- **Link traversal.** N-tier BFS, only when `_is_custom(chain)` (any link edge or >3 nodes); else the existing 2-query path runs unchanged. `parent` edges use batched `parent in (...)` JQL; `link` edges read the `issuelinks` field (added to the fetched field list), keep entries whose `type.name ∈ node.link_types` (either direction), and batch-fetch targets by `key in (...)`. Cross-tier `seen` set + `max_tier` bound guard cycles/fan-out. `apply_hierarchy()` sets `display_tier` per type and AND-resolves the show/estimate cascade up `hierarchy_parent_key`.
- **Icons.** In-memory `dict[type_id -> bytes]` on `JiraClient`, lazily `GET`-ing each `iconUrl` via `self._jira._session`, cleared by `invalidate_caches`. At render time the used SVGs are written into the Typst temp project dir (`root/icons/<id>.svg`) since typst-py has no in-memory FS; templates reference `image("icons/<id>.svg")` with a fixed icon box + gap so nothing overlaps. Emit an icon string only when bytes are cached (Typst `image()` hard-errors on a missing path).
- **Reuse map (modify, don't reinvent):** drag-reorder list `_ChildRowList`/`_DragHandle`/`_ChildRow` (widgets.py:1301/589/1133); cascade greying `_sync_enabled` run per-toggle (widgets.py:1243); flat icon buttons `_icon_btn` (widgets.py:150); `CollapsibleSection` (widgets.py:362); `no_scroll_wheel` + `addItem/findData` combos (widgets.py:73); `exec_dialog`/`make_dialog_button_box` (widgets.py:131/108); epic completer reuses `_apply_completer` (widgets.py:742); background fetch reuses `ThreadedTask` + the `_detect_fields` flow (config_panel.py:1457); raw REST mirrors the `/rest/api/3/label` `_session` block (jira_client.py:574); metadata via `issue_types()`/`issue_link_types()`; cache invalidation extends `invalidate_caches` (jira_client.py:94); compact serialize mirrors `_serialize_override`/`_coerce_overrides` (widgets.py:527-581); config batch via `ConfigManager.batch()` (config_manager.py:141); SVG→pixmap via `QPixmap.loadFromData`.
- **Deliberately NOT built (kept minimal):** no persistent disk icon cache (in-memory bytes); no unified fetch path (keep the fast default path); no new `IconCache` class; chain not stored on `ChildOverride` (orthogonal). SP roll-up stays single-level (2-tier today too).
- **Gaps closed during review:** thread `ReportConfig.issue_hierarchy` from `preview_panel._generate_report` into the fetch entry points, `calculate_metrics`, and `merge_metrics` (label-group synthetic epics also use `hierarchy_parent_key`/`in_estimate`); the constructor auto-fetches types on first open (and shows a Refresh prompt when empty/disconnected); per-item `child_overrides` (`_resolve_children` in preview_panel) continue to apply on top of chain-traversed children (orthogonal — confirm with a test).
- **Corner cases & semantics (resolved in the second review pass):**
  - **`in_estimate` semantics.** `in_estimate=False` mirrors today's `include_subtasks=False`: the issue is dropped from metrics entirely (so it affects neither estimate weight nor the done/total **count**), across all three `progress_method` values (`combined`/`issues_only`/`estimates_only`, metrics.py:99/115). `show` is purely display. This preserves the two-axis model (e.g. sub-tasks `show=False, in_estimate=True` roll up but aren't displayed; `show=True, in_estimate=False` displayed but not counted).
  - **Default-path subtask fetch.** The fast 2-query path gates subtask fetching on `need_subtasks = include_subtasks or include_subtasks_in_timeline` (jira_client.py:821). With the flags gone, derive it from the migrated chain — fetch the Sub-task tier when its node has `show` **or** `in_estimate`. Keep `_drop_subtasks` (jira_client.py:66/850) for the show-only-on-timeline case.
  - **Customize-children dialog respects the chain.** `fetch_child_summaries` (jira_client.py:500, used by `ChildCustomizeDialog` at config_panel.py:1210/1363/1429) is `parent`-only today; it must list the **chain-children** of an item (e.g. link-connected `Feature`s under a `Capability`) for the relevant tier. Add a chain-aware path mirroring `_fetch_epics_chain` (single-level), defaulting to today's `parent` query when the chain is the default.
  - **Timeline date pooling (corrected).** Today `_fill_epic_dates_from_children` (jira_client.py:608) and the metrics date filter (metrics.py:298) pool **tier-1 (direct-child) dates always** but include **tier-2 (sub-task) dates only when `include_subtasks_in_timeline`** is set (`if c.is_subtask and not include_subtask_timeline: continue`). Generalize the gate to `display_tier == 2 and not show`: tier-1 always pools; a tier-2 child expands the epic range only when shown. Since migration sets sub-task `show=False`, the default Gantt range stays byte-for-byte identical. (Pooling *all* children regardless of `show` would wrongly stretch every default epic range — do NOT do that.)
  - **Nested summary rows carry the certainty column** (the same per-child `scope_certainty` from `child_overrides` / `average_certainty`), and **label groups** render group-header → epic → nested chain children consistently with `expand_label_details`.
  - **Guards.** The chain must always contain ≥1 Epic-tier (tier 0) node (UI enforces; `epic_tier_type_names` therefore never returns `[]`); each issue type appears at most once in the chain (UI prevents duplicates; the type→node map is 1:1).
  - **Chain validation.** Extend the Validate action / Refresh to flag chain nodes whose issue type or link type no longer exists in Jira after an instance change (warning, not error).
  - **Offline migration fallback.** Default-chain derivation needs `hierarchyLevel`, which requires Jira; when metadata is unavailable at config-restore time, fall back to the classic `Epic→Story→Sub-task` names/tiers and refine on the next successful Refresh.
  - **Minor:** issue-type icons may also be shown on the report-item config rows (optional); SVG icons keep their own colors, so confirm legibility on a dark-themed report (rare — report defaults to light).

## Implementation Steps

### Task 1: Data model and serialization

- [x] Add the `HierarchyNode` dataclass and `ReportConfig.issue_hierarchy` field in `core/data_models.py`
- [x] Add `hierarchy_parent_key`, `display_tier`, `issue_type_id`, and effective `show`/`in_estimate` fields to `JiraIssue`
- [x] Add compact serialize/coerce helpers for the chain, mirroring the default-omitting `_serialize_override`/`_coerce_overrides` pattern
- [x] Add the `epic_tier_type_names(chain)` helper (defaults to `["Epic"]` when the chain is empty)
- [x] write tests for serialize↔coerce round-trip and the epic-tier helper
- [x] run project tests - must pass before next task

### Task 2: Jira client metadata, icons, and issue picker

- [x] Add `fetch_issue_types()` and `fetch_issue_link_types()` (via the `jira` lib methods, with `getattr` fallbacks), cached in-memory
- [x] Add `fetch_issue_picker(query, current_jql)` mirroring the raw `/rest/api/3/label` `_session` call
- [x] Add `issue_type_icon(type_id) -> bytes | None` with an in-memory bytes cache fetched via `self._jira._session`
- [x] Extend `invalidate_caches()` to clear the new type/link/icon caches
- [x] write tests for metadata parsing and cache invalidation (against a recorded payload)
- [x] run project tests - must pass before next task

### Task 3: Jira client N-tier chain fetch and label scope

- [x] Add `_is_custom(chain)` and `_fetch_epics_chain(...)`; route the three fetch entry points to it only for custom chains, leaving the default 2-query path untouched
- [x] Implement BFS traversal: `parent` edges via batched JQL; `link` edges by reading `issuelinks` and batch-fetching targets by key; add `issuelinks` to the fetched field list
- [x] Add cross-tier `seen` set and `max_tier` bound to guard cycles/fan-out
- [x] Add `apply_hierarchy()` to set `display_tier` and AND-resolve the show/estimate cascade up `hierarchy_parent_key`
- [x] Change the label-fetch JQL to `issuetype in (<epic-tier names>) AND labels = ...` with an `epic_tier_types` param (default `["Epic"]`); update the label call sites to pass the derived list
- [x] Make `fetch_child_summaries` chain-aware (list the chain-children for the relevant tier, e.g. link-connected children), defaulting to today's `parent` query for the default chain — the customize-children dialog relies on it
- [x] Derive the default-path subtask fetch from the migrated chain (fetch the Sub-task tier when its node has `show` or `in_estimate`), replacing the removed `need_subtasks` flag while keeping `_drop_subtasks`
- [x] write tests for parent+link traversal, cascade resolution, multi-type label scope, and chain-aware child summaries
- [x] run project tests - must pass before next task

### Task 4: Metrics generalization

- [x] Replace `parent_key` reads with `hierarchy_parent_key` in the subtask-map build, `_subtask_keys`, and the date-cascade code, including `merge_metrics` for label groups
- [x] Drop `in_estimate=False` issues from metrics entirely (no weight, no done/total count) across all three `progress_method` values — mirroring today's `include_subtasks=False`; `show` stays display-only
- [x] Generalize the `is_subtask`-gated date filters (`_fill_epic_dates_from_children` jira_client.py:608, metrics.py:298) to `display_tier == 2 and not show` — tier-1 dates always pool, tier-2 dates expand the epic range only when shown — preserving today's `include_subtasks_in_timeline` default; read `c.show` instead of the removed global flag
- [x] Confirm `_compute_all_issue_progress` recursion handles N tiers
- [x] write tests including a 4-tier progress roll-up, a windowed metrics case, the `in_estimate` axis under each progress method, and tier-2 date pooling (excluded by default, included when a sub-task is shown)
- [x] run project tests - must pass before next task

### Task 5: View-model and PDF payload

- [x] Emit nested summary child rows for visible (`show`) children in hierarchy order with `depth`/`icon`, keeping aggregate rows and the KPI strip epic-level
- [x] Carry the per-child scope-certainty onto nested summary rows, and render label groups as group-header → epic → nested chain children consistently with `expand_label_details`
- [x] Replace the global timeline show flags with per-child `show`, indenting by `display_tier`, and add `icon` to timeline items
- [x] Thread an `icon` field (or `""`) onto epic/child/page dicts, only when icon bytes are cached
- [x] Gather the used icon bytes in `pdf_generator` and pass them to the renderer; thread `issue_hierarchy` from `preview_panel._generate_report` into the fetch + metrics calls
- [x] write tests for nested-row emission and the icon-present guard
- [x] run project tests - must pass before next task

### Task 6: Typst rendering and icons

- [x] Have `typst_renderer` write used icon SVGs into `root/icons/<id>.svg` after the template copytree
- [x] Add a child-row branch to `summary.typ` with indent + boxed icon + key/summary (fixed padding, no overlap)
- [x] Add the icon to `gantt.typ` rows and the `epic.typ` detail header with a consistent icon box + gap
- [x] write a render self-check (including a missing-icon case) and a default-chain output comparison
- [x] run project tests - must pass before next task

### Task 7: Issue Hierarchy constructor UI

- [x] Build `IssueHierarchyEditor` in a `CollapsibleSection` in Step 1 (after Report Items, before Jira Field Mapping), reusing `_ChildRowList`/`_DragHandle`/`_ChildRow`
- [x] Render each active node row with icon+type combo, edge combo (`parent`|`link`), link-type multi-select chips (shown only for `link`), tier dropdown, and the two `Show`/`Estimate` checkboxes
- [x] Apply down-chain cascade greying via `_sync_enabled` run per-toggle (separately for visibility vs estimate)
- [x] Add the divided Exclude area with drag between it and the active chain; auto-fetch types on first open and show a Refresh prompt when empty/disconnected
- [x] Add the Refresh-from-Jira button using the `ThreadedTask`/`_detect_fields` background pattern, repopulating panes and clearing caches
- [x] Enforce guards: at least one Epic-tier (tier 0) node; no duplicate issue type in the chain
- [x] On Validate/Refresh, warn (not error) when a chain node references an issue type or link type that no longer exists in Jira
- [x] Remove the four global toggle widgets and their persistence
- [x] write tests where feasible (serialization of editor state, cascade logic helper)
- [x] run project tests - must pass before next task

### Task 8: Epic autocomplete by key and summary

- [x] Wire the report-item key field for `kind == "epic"` to a debounced `ThreadedTask` calling `fetch_issue_picker` scoped to `issuetype in (<epic-tier names>)`, reusing `_apply_completer`
- [x] Show `KEY — summary` suggestions, set the key on pick, and cancel in-flight tasks (never block the UI)
- [x] Swap the completer when a row's kind changes (epic → issue picker scoped to Epic-tier types; label → existing `/label` completer)
- [x] write tests for the suggestion model wiring where feasible
- [x] run project tests - must pass before next task

### Task 9: Config plumbing and migration

- [x] Add `issue_hierarchy` to `PROFILE_KEYS` and `_DEFAULTS`, and thread it through `get_report_config`, `_restore_values`, `_do_persist`, and `reset`
- [x] Implement migration: when a profile has no chain, derive `Epic→Story→Sub-task` from `hierarchyLevel` and map the four old booleans to node `show`/`in_estimate` flags so default output stays identical; keep reading old keys for back-compat, write only `issue_hierarchy`
- [x] Handle the offline case: when Jira metadata is unavailable at config-restore, fall back to the classic `Epic→Story→Sub-task` names/tiers and refine on the next successful Refresh
- [x] write tests asserting the migration yields output identical to the pre-change behavior (and the offline fallback chain)
- [x] run project tests - must pass before next task

### Task 10: User guide standardization

- [x] Standardize every configurable control to a table row (`Control | Default | What it does`); convert blockquote/inline toggle docs to tables
- [x] Add an "Issue Hierarchy" section (chain, edges, Exclude area, Show/Estimate toggles, Refresh, icons) and relocate the per-type toggle docs out of the Estimation/Report content/Timeline sections
- [x] verify the guide renders correctly in the in-app Help panel
- [x] run project tests - must pass before next task

### Task 11: Verify acceptance criteria

- [x] Verify all requirements from Overview are implemented (custom chain, per-type cascade, Exclude area, icons, autocomplete, label scope, migration, docs) — all symbols present (`HierarchyNode`, `issue_hierarchy`, `_is_custom`/`_fetch_epics_chain`, `apply_hierarchy`, `_ExcludedTypeRow`/`IssueHierarchyEditor`, `issue_type_icon`, `fetch_issue_picker`, `epic_tier_type_names`, classic-chain migration in `config_manager`, user-guide "Issue hierarchy" section) and exercised by the passing suite
- [x] Generate a report with the default chain and confirm the PDF is identical to a pre-change baseline — automated default-chain identity tests pass (`test_default_chain_text_unchanged`, `test_default_chain_emits_no_child_rows`, `test_default_chain_uses_epic_link_and_parent`, migration-identity tests); full byte-identity against a saved on-disk PDF baseline is manual (skipped - not automatable here)
- [x] manual visual (skipped - not automatable): custom chain eyeball of summary nested rows / timeline bars / icon padding / detail headers — render path covered by `test_custom_chain_with_icons_renders` + summary/gantt/epic self-checks
- [x] Exercise corner cases — all covered by passing unit tests: `test_link_edge_lists_linked_children`/`test_default_chain_uses_epic_link_and_parent` (customize-children chain), `test_in_estimate_false_dropped_from_metrics` (in_estimate under each method), tier-2 date pooling (`test_cascade_and_tier_assignment`), classic-chain offline fallback (`test_default_flags_classic_chain`), `test_hierarchy_editor_stale_warning` (Validate stale ref)
- [x] live read-only Jira check (skipped - not automatable): blocked by the rejected GlobalLogic scoped token (401); cannot run live. Re-run per Post-Completion when a valid token is available
- [x] run full project test suite — 592 passed
- [x] run project linter - isort clean on all feature files; black "issues" are repo-wide newer-black (26.5.1) line-collapse churn that also flags untouched files (e.g. `main_window.py`, `test_install_source.py`), so the feature code matches the repo's committed style baseline — no feature-introduced lint issues

## Post-Completion

*Items requiring manual intervention - no checkboxes, informational only*

- Re-run the live read-only verification only against an instance whose API token is valid (the user's scoped token authenticates via the cloud API base).
- Communicate the behavior change to any user who had explicitly enabled "show stories/subtasks on timeline": those profiles now also gain nested child rows on the summary.
