# urhox-voxel-replication

**Repository:** https://github.com/Ecnahc1014-xd/urhox-voxel-replication

Image-driven and design-driven voxel replication workflows for UrhoX/TapTap Maker. The package turns visual fidelity, registration, occupancy, projection, runtime evidence, and delivery claims into auditable, reproducible artifacts.

World contracts are parameterized, not hard-coded to one target: the unit voxel cube size (single constant, integer grid, explicit quantization tolerance, resampling on size change) and the character↔voxel correspondence (standing height = whole number of unit cubes) are strong rules registered in `references/08` §3.1. No claim is made about any specific downstream engine's file formats.

## Contents

- `docs/TOOL-OVERVIEW.md` — tool overview: the three headline advantages, package structure, up/downstream map, gates, results, reading boundaries
- `docs/DEFECTS-AND-LEDGER.md` — defects, capability gaps and the per-round verification ledger
- `SKILL.md` — routing entry and operating contract
- `references/` — normative workflow and adapter chapters
- `scripts/` — executable checks and instruments
- `cases/` — example snapshots, not thresholds
- `evals/` and `tests/` — evaluation contracts and deterministic regression checks

## Validate

Run from this directory with Python 3.12 or the interpreter bound by the project:

```powershell
$env:PYTHONUTF8 = "1"
python tests/run_tests.py --json --project-root <project-root>
```

For a portable package-only check, use `--skip-environment --skip-external`. A skipped check remains skipped; it is not a complete release pass. Add `--require-complete` for a release gate.

The Skill frontmatter can be checked with `quick_validate.py` from `skill-creator`.

## Scope

This repository contains workflow instructions, scripts, test fixtures, and documentation. It does not include proprietary game assets, player saves, or copies of third-party reference projects.
