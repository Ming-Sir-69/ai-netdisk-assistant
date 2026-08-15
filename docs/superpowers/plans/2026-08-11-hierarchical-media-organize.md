# Hierarchical Media Organize Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `panlib-organize` execute the Skill contract `类型根 / 宇宙（可选）/ 作品系列（可选）/ 内容单元 / 文件` for episodic media and exact multi-movie manifests without guessing identities or overwriting cloud data.

**Architecture:** Keep the existing single-item CLI flags as a compatibility path, but route new multi-item work through a versioned JSON manifest. A focused `panlib/media_manifest.py` module validates structured identity and computes canonical target paths. `panlib-organize` remains plan-first, emits a `plan_ref` for manifest plans, builds missing parents in order, executes exact actions fail-fast, and verifies every target directory independently.

**Tech Stack:** Python 3.13, stdlib `argparse/json/hashlib/dataclasses/pathlib`, existing `panlib.common`, existing fake `bdpan`, `unittest`.

## Global Constraints

- Agent only calls `scripts/` and `bin/panlib-*`; production code never reads local bdpan configuration.
- No delete, overwrite, automatic retry, arbitrary full-drive movement, or direct `bdpan` invocation.
- All cloud paths remain under configured `BDPAN_BASE`; `ondup` behavior stays fail-fast/no-clobber.
- Universe keys are only `marvel`, `dc`, or `null`, mapping exactly to `Marvel Cinematic Universe` and `DC Cinematic Universe`.
- The fixed hierarchy is `类型根 / 宇宙（可选）/ 作品系列（可选）/ 内容单元 / 文件`.
- Movie item folder: `{内容规范名}.{年份}.{IMDb ID}`; episode season folder: `{作品规范名}.Sxx`.
- Episode file: `{内容规范名}.SxxExx.{imdb-IMDb ID}.{清晰度}.{扩展名}`.
- `MCU` is not a valid directory name; `season-folder-style` is not configurable.
- Manifest execution requires exact source path plus available identity fields (`fs_id`, `size`) and a matching `plan_ref`.
- Filename parsing may propose metadata but may not authorize a movie move; movie identity comes from the manifest.
- Existing dirty worktree changes belong to the user. Do not revert them, commit them, or push them in this task.
- No real Baidu Netdisk mutation is part of implementation verification; real E2E is a separate user-authorized validation.

---

### Task 1: Canonical hierarchy naming primitives

**Files:**
- Modify: `panlib/naming.py`
- Test: `tests/test_naming.py`

**Interfaces:**
- Produces: `UNIVERSE_DIRS`, `build_work_folder_name(canonical_title) -> str`, `build_season_folder_name(canonical_title, season) -> str`, and category root validation used by Task 2.
- Preserves: existing movie folder and media filename builders.

- [x] **Step 1: Write failing naming tests**

Add literal expectations for `marvel -> Marvel Cinematic Universe`, `dc -> DC Cinematic Universe`, `Loki`, `Moon Knight`, `Loki.S01`, `Moon.Knight.S02`, invalid universe keys, and invalid season numbers.

- [x] **Step 2: Run the focused tests and observe RED**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_naming -v`

Expected: failure because the hierarchy primitives do not exist.

- [x] **Step 3: Implement the minimum naming primitives**

Use the existing title/path validators. Collection/work folders preserve canonical word spaces; season item folders replace title spaces with dots and append `.Sxx`.

- [x] **Step 4: Run the focused tests and observe GREEN**

Run the same command; all naming tests must pass.

### Task 2: Versioned manifest validation and target planning

**Files:**
- Create: `panlib/media_manifest.py`
- Create: `tests/test_media_manifest.py`

**Interfaces:**
- Consumes: Task 1 naming primitives and `Settings`/path validators from `panlib.common`.
- Produces: `load_media_manifest(path, settings, source_dir)`, normalized manifest dictionaries, exact target paths, collision-free item identities, and `manifest_plan_ref(normalized_manifest, snapshots)`.

Manifest v1 shape:

```json
{
  "version": 1,
  "category": "movie | tv | anime | documentary | webdrama",
  "universe": "marvel | dc | null",
  "collection": "规范作品或系列名 | null",
  "items": [
    {
      "source_path": "/apps/bdpan/片库/Movies/incoming/1. X-Men.2000.mkv",
      "fs_id": 123,
      "size": 456,
      "layout": "single | episode | season",
      "canonical_title": "X-Men",
      "year": "2000",
      "imdb_id": "tt0120903",
      "season": null,
      "episode": null,
      "quality": "1080p"
    }
  ]
}
```

- [x] **Step 1: Write failing manifest tests**

Cover Marvel/DC mapping, Loki season targets, X-Men series targets, source containment, exact source identity, duplicate sources, duplicate targets, malformed JSON/version, forbidden arbitrary universe/category, missing movie year, missing episode numbers, and the removal of numeric source prefixes from canonical output.

- [x] **Step 2: Run the new test module and observe RED**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_media_manifest -v`

Expected: import failure because `panlib.media_manifest` does not exist.

- [x] **Step 3: Implement strict manifest normalization**

Limit input size, require one JSON object with version `1`, reject unknown keys that can alter destinations, derive extensions from the exact discovered source, require manifest `fs_id`/`size` to equal the live source when supplied, and build all paths through safe cloud joins.

- [x] **Step 4: Add deterministic plan fingerprinting**

Hash a stable JSON representation of the normalized manifest plus sorted source/target snapshots. The hash is a 64-character lowercase SHA-256 string.

- [x] **Step 5: Run the manifest tests and observe GREEN**

Run the same test command; all manifest tests must pass.

### Task 3: Hierarchical TV planning and numeric episode mapping

**Files:**
- Modify: `bin/panlib-organize`
- Modify: `tests/test_organize_cli.py`

**Interfaces:**
- Legacy movie mode remains unchanged.
- Legacy `tv`/`season` mode treats `--target-dir` as the work collection directory and creates `{作品规范名}.Sxx` item directories below it.
- Adds `--expected-episodes N`; it only enables strict pure-numeric episode fallback.

- [x] **Step 1: Write failing CLI behavior tests**

Cover Loki S01/S02 actions, ordered parent/season mkdir, per-season conflict reads, plan-only no mutation, execute order, TOCTOU, partial failure, and post-state. Add Falcon fixtures for `01.mp4` through `06.mp4` with `--season 1 --expected-episodes 6`.

- [x] **Step 2: Run focused organize tests and observe RED**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_organize_cli -v`

Expected: flat target behavior and unknown numeric episodes fail the new literal expectations.

- [x] **Step 3: Implement season-aware actions**

Plan every source into its own season directory, deduplicate mkdir actions, and make destination checks use each action's actual target directory instead of one global target.

- [x] **Step 4: Implement strict numeric fallback**

Only map numeric video stems when every video stem is numeric, values are exactly `1..N`, `N == --expected-episodes`, there are no parsed/numeric mixtures, and season is positive. Use the numeric value as the episode number; otherwise return `INVALID_ARG` before mutation.

- [x] **Step 5: Run focused tests and observe GREEN**

Run the same test command; all organize tests must pass.

### Task 4: Exact manifest execution for multi-movie and mixed layouts

**Files:**
- Modify: `bin/panlib-organize`
- Modify: `tests/test_organize_cli.py`
- Test: `tests/test_media_manifest.py`

**Interfaces:**
- Adds `--manifest-file PATH` and `--plan-ref HASH`.
- `--manifest-file` is mutually exclusive with legacy title/target metadata. `--source-dir` remains mandatory.
- Manifest plan-only returns normalized targets, complete ordered actions, `plan_ref`, and `executed=false`.
- Manifest execute requires the matching `--plan-ref`; it rebuilds the plan from fresh cloud state before the first mutation.

- [x] **Step 1: Write failing multi-item plan tests**

Use a flat X-Men fixture with numeric source prefixes and two different IMDb identities. Assert exact universe/collection/movie item paths, canonical filenames without prefixes, ordered mkdirs, and no write calls in plan-only mode.

- [x] **Step 2: Write failing execution safety tests**

Cover missing/wrong plan_ref, source fsid/size drift, target appearance after plan, duplicate target, mkdir partial state, move/rename partial failure, exact completed actions, no retry, no delete, and final per-item target verification.

- [x] **Step 3: Run focused tests and observe RED**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_media_manifest tests.test_organize_cli -v`

- [x] **Step 4: Implement manifest CLI mode**

Build plans using `panlib.media_manifest`, create missing directories one level at a time, execute exact source actions only, and retain legacy behavior when no manifest is supplied.

- [x] **Step 5: Run focused tests and observe GREEN**

Run the same command; all focused tests must pass.

### Task 5: Public contract, regression, and synchronization

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `docs/CLI_CONTRACT.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `tests/test_docs_contract.py`

**Interfaces:**
- Documents manifest v1, fixed universe names, work/season hierarchy, strict numeric fallback, plan_ref, and legacy compatibility.

- [x] **Step 1: Add failing consumer-facing contract tests**

Assert documented CLI arguments and outputs through `--help`/controlled invocation where possible; keep prose-only assertions limited to Agent state-machine requirements.

- [x] **Step 2: Run docs/setup tests and observe RED**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_docs_contract tests.test_setup_scripts -v`

- [x] **Step 3: Update all public contracts**

State that new hierarchy writes use manifest mode, `MCU` is invalid, numeric fallback is conditional, filename-only movie identity is never sufficient, and existing flat directories require a fresh manifest migration plan.

- [x] **Step 4: Run affected and full regression suites**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.test_naming tests.test_media_manifest tests.test_organize_cli tests.test_docs_contract tests.test_setup_scripts -v
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

Network-dependent failures must be reported separately and may not be relabeled as passing.

- [x] **Step 5: Run release-adjacent static gates**

Run `py_compile`, `git diff --check`, the whole-tree privacy guard, Skill quick validation, and verify the CC Switch and WorkBuddy symlinks resolve to the same canonical repository.
