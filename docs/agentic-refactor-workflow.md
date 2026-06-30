# Agentic refactor workflow

This repository is a support tool for agents and reviewers. It should be run outside the target fasm2/fasmg-style source tree, then used to plan, execute, and verify small refactors.

## 1. Establish a baseline

Run the analyzer into a stable output directory before editing the target project:

```sh
python -m fasm2_structure /path/to/target source/windows examples tests/ntdll \
  --report --advice --plan --plan-limit 8 \
  --out /path/to/baseline-analysis
```

Keep at least these baseline artifacts:

- `report-data.json`
- `refactor-advice.md`
- `refactor-plan.md`
- `report.html`

## 2. Pick a scoped task

Use `refactor-plan.md` as the task queue. Prefer one task per commit.

A good first task has:

- high `refactor_score`
- high `abi_pressure`
- a source path inside the intended scope
- a verification path you can actually run

Skip tasks in examples, generated code, or out-of-scope modules unless those are the intended target. Use `--plan-limit` to keep a delegation batch small, and tune `--medium-pressure` / `--high-pressure` if the default thresholds are too high or low for the target corpus.

## 3. Inspect before editing

For the chosen task:

1. Read the whole routine and surrounding helpers.
2. Open `report.html` and focus the function neighborhood at depth 1.
3. Increase to depth 2 only after the direct callers/callees are understood.
4. Identify whether the issue is:
   - parameter/register state surviving ABI calls
   - repeated ABI boundary calls in orchestration code
   - low-level helper code depending on high-pressure ABI behavior
   - a large or cross-file SCC

## 4. Refactor conservatively

Use the metric as a navigation signal, not as a correctness oracle.

Common safe moves:

- split pre-ABI argument preparation from ABI invocation
- split post-ABI state handling from boundary calls
- introduce clearer local/state names where register lifetime is implicit
- move ABI interaction upward or behind a narrow adapter
- extract pure utilities only when they remain ABI-independent

Avoid:

- changing semantics only to lower `abi_pressure`
- collapsing useful wrappers because they have low pressure
- mixing multiple pressure targets in one commit
- accepting a pressure decrease without target-project build/smoke verification

## 5. Verify the target project

Run the target project's relevant build, assembler, test, or smoke command. If no full test exists, record the best available command and its limitation.

## 6. Re-run analysis and compare

Generate a fresh post-refactor analysis and compare it to the baseline:

```sh
python -m fasm2_structure /path/to/target source/windows examples tests/ntdll \
  --report --advice --plan \
  --compare-report /path/to/baseline-analysis/report-data.json \
  --out /path/to/after-analysis
```

Review:

- `refactor-compare.md`
- `refactor-advice.md`
- `refactor-plan.md`
- `report.html`

The comparison gate should answer:

- Did the target's pressure or fan-out decrease?
- If pressure increased, did it move behind a clearer boundary?
- Did new regressions appear in unrelated functions?
- Did the target project's own verification pass?

## 7. Commit with evidence

A useful commit message/body includes:

- target function/module
- before/after pressure summary
- target-project verification command
- analyzer comparison output path or copied summary

Example body fragment:

```text
Structure analysis:
- target: source/windows/dll/system.inc:get_environment_variable
- before: abi_pressure 87, class abi_state_pressure
- after: abi_pressure 42, class abi_state_pressure
- comparison: no unrelated regressions

Verification:
- ./tools/build_example.sh examples/...
- python -m fasm2_structure ... --compare-report ...
```

## Agent prompt template

When delegating a refactor to an implementation agent, include:

```text
You are refactoring a fasm2/fasmg-style assembly target using fasm2-agent-structure-tools.

Scope:
- Target repo: <path-or-url>
- Target function/task from refactor-plan.md: <task id and scope>
- Baseline report-data.json: <path>
- Target verification command: <command>

Required workflow:
1. Read the full target routine and direct neighborhood before editing.
2. Use the task's suggested action, but preserve semantics over lowering metrics.
3. Run the target verification command.
4. Regenerate analysis with --report --advice --plan --compare-report <baseline>.
5. Report before/after ABI pressure, regressions, and verification output.

Do not edit unrelated pressure targets in the same commit.
```
