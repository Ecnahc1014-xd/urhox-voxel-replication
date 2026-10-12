# Package checks

run_tests.py is the deterministic package-level check. Run it from the package root or pass explicit roots:

    PYTHONUTF8=1 python tests/run_tests.py --json --project-root URHOX_REPLICATION_ROOT

For a portable package-only check, use --skip-environment. If the external reference archive is not mounted, add --skip-external; the report then records those checks as skipped rather than calling them green. Add --require-complete when a release gate must reject every skipped check.

The runner checks the evals/evals.json contract, the answer-free tests/forward_eval_cases.json pack, and all script --help interfaces, but it does not pretend that declaration checks are behavior evaluation. Forward evals must be run by an independent agent against realistic user requests and isolated artifacts; use tests/forward_eval_protocol.md for the scoring rubric.

test_behavior_artifacts.py runs real subprocesses on an asymmetric occupancy fixture, known binary masks and actual feature-tag files. It checks measured areas/intersection/union, rejects degenerate masks, missing requested CAD backends and invalid labels, and verifies a shared drawing scale within sheet cells. These regressions test tool behavior, not game-scene fidelity or overall skill quality.
