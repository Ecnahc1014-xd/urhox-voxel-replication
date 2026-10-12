# urhox-voxel-replication

Image-driven and design-driven voxel replication workflows for UrhoX/TapTap Maker. The package turns visual fidelity, registration, occupancy, projection, runtime evidence, and delivery claims into auditable, reproducible artifacts.

It also includes a downstream adapter chapter for **Xdanger S2** fixed-template worlds, world snapshots, and reusable scene/personal/functional components. The Xdanger chapter is an adapter contract; it does not claim direct import, publishing, sharing, cloud sync, or native runtime support without target-project evidence.

## Contents

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

This repository contains workflow instructions, scripts, test fixtures, and documentation. It does not include proprietary game assets, player saves, or a copy of the Xdanger project.
