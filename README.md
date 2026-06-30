# fasm2 agent structure tools

[![CI](https://github.com/sit-d/fasm2-agent-structure-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/sit-d/fasm2-agent-structure-tools/actions/workflows/ci.yml)

Python static-analysis helpers for reviewing fasm2/fasmg-style assembly source trees from outside the target repository. The tools are intended for agents and reviewers that need higher-level structure signals before suggesting multi-file implementation changes.

See [`docs/agentic-refactor-workflow.md`](docs/agentic-refactor-workflow.md) for the full baseline → task-card → target verification → before/after comparison loop.

The first pass is intentionally heuristic and source-preserving. It does not try to fully expand fasm2/fasmg macros. Instead it extracts enough structure to guide review and implementation planning:

- function/data graph: calls, ABI calls, unresolved/indirect calls, and data references
- ABI pressure score: integer `abi_calls + parameter_uses_after_abi_call`
- hierarchy/layering: Tarjan SCCs and leaf-first condensation layers
- visual reports that make questionable structure decisions easier to spot
- agentic refactor advice and task plans that turn the metrics into prioritized review actions

## Install / run from source

From this tool repository:

```sh
uv run --with pytest pytest -q
python -m fasm2_structure /path/to/fasm2-or-fasmg-source --report --advice --plan
```

Example for analyzing only selected subtrees of a target repo:

```sh
python -m fasm2_structure /path/to/fasm2 source/windows examples tests/ntdll --report --advice --plan --plan-limit 5
```

Use a narrower path while iterating:

```sh
python -m fasm2_structure /path/to/fasm2 source/windows/fasmg.asm source/windows/system.inc --out analysis/windows-core
```

Outputs are written under the target root by default, or under `--out` if supplied:

- `structure.json` — symbols, edges, and function ABI pressure metrics
- `layers.json` — Tarjan SCCs and leaf-first implementation layers
- `structure.dot` — Graphviz DOT for the function/data graph
- `report.html` — self-contained interactive structure report
- `report-data.json` — browser/report data model
- `mermaid/scc-condensation.mmd` — focused SCC condensation graph
- `mermaid/module-graph.mmd` — module/directory dependency graph
- `mermaid/top-pressure.mmd` — top ABI-pressure neighborhood snapshot
- `refactor-advice.json` — machine-readable prioritized agent guidance
- `refactor-advice.md` — human-readable refactor review plan
- `refactor-plan.json` — machine-readable scoped refactor task cards
- `refactor-plan.md` — human-readable task plan with steps and verification gates
- `refactor-compare.json` / `refactor-compare.md` — before/after pressure movement when `--compare-report` is used

Internal calls made through ABI-style macros are emitted as `abi-call`: they contribute to both ABI pressure and the function dependency graph.

## ABI pressure interpretation

The primary implementation-dynamics metric is an integer:

```text
abi_pressure = abi_calls + parameter_uses_after_abi_call
```

`abi_pressure = 0` means a pure leaf routine: no ABI calls were detected, so no ABI frame is needed by the heuristic. This gives pure leaf functions a distinct control surface for code-generation dynamics.

`abi_pressure = 1` commonly means one ABI boundary with no detected parameter survival afterward. Check `pressure_class` and `tail_abi_calls` to distinguish tail-call wrappers from normal ABI boundaries.

Higher values mean more ABI boundaries and/or more evidence that incoming parameter/register state survives across them. This acts as a simple register/frame pressure signal for implementation planning.

The analyzer also emits `pressure_class`:

- `pure_leaf` — `abi_pressure == 0`
- `tail_abi` — all ABI interactions are tail-position and no parameters survive afterward
- `abi_boundary` — ABI calls exist, but no parameter survival is observed
- `abi_state_pressure` — parameter evidence survives after ABI calls; implementation may need frame/register choreography

The component counts remain in JSON so ranking can be adjusted later without losing evidence.

Current parameter evidence includes:

- declared `proc` parameters when visible
- common ABI parameter registers (`rcx`, `rdx`, `r8`, `r9`, `ecx`, `edx` variants)
- stack parameter patterns such as `[rbp+...]` / `[ebp+...]`

## Layering interpretation

`layers_leaf_first` in `layers.json` is ordered for implementation work:

- layer 0: routines with no internal function dependencies
- higher layers: routines that depend on previous layers
- SCC entries with multiple functions are recursive/mutually recursive islands and should be planned together

## Visual report

Use `--report` to generate visual tooling aimed at making poor structure decisions obvious. The HTML report is static and can be opened directly in a browser.

The report includes:

- SCC/layer condensation view, colored by ABI pressure
- module graph, aggregated by top source/example/test subdirectory
- function neighborhood view with selectable depth
- filters for search text, minimum ABI pressure, and hiding pure leaves
- pressure table synchronized with graph focus
- structure smell list for high ABI pressure, high pressure in leaf layers, recursive SCCs, and cross-file SCCs

The Mermaid files are intentionally focused snapshots. They are useful for documentation and quick sharing, while the HTML report is better for choosing the right depth interactively.

## Agentic refactor advice

Use `--advice` when an agent should use the structure data to review code and propose or execute refactors. The advice generator combines ABI pressure, call fan-out, fan-in, SCC/layer placement, module hotspots, and structure smells.

The generated `refactor-advice.md` is intentionally action-oriented:

- start with the highest `refactor_score` item in the intended scope
- inspect the HTML report at depth 1, then depth 2
- split `abi_state_pressure` routines into pre-ABI preparation, ABI boundary calls, and post-ABI state use
- keep high-pressure routines out of low-level leaf layers where possible
- use pure utilities as safe extraction/reuse candidates
- regenerate advice after a refactor and check whether pressure moved down or became better isolated

Use `--plan` with `--advice` when an agent needs concrete task cards. The plan expands the highest-priority pressure targets into one-target-per-task scopes with expected outcomes, steps, and verification gates. Use `--plan-limit N` to cap the queue for a small agent batch, and tune `--medium-pressure` / `--high-pressure` when the target project is much smaller or larger than the fasm2 baseline. The JSON forms are better for automated agents; the Markdown forms are better for human review notes or PR comments.

After a refactor, compare the new analysis against a previous `report-data.json`:

```sh
python -m fasm2_structure /path/to/fasm2 source/windows --report --advice --plan --compare-report /path/to/before/report-data.json --out analysis/after
```

The comparison report summarizes total ABI-pressure movement, improved/worsened functions, added/removed functions, and the largest per-function pressure changes. Treat regressions as a review gate, not an automatic failure: some refactors intentionally move pressure behind a clearer boundary.

## Known limitations

- Macro expansion is not performed; edges are lexical evidence.
- Local labels are not modeled as separate functions unless they start at column 0.
- ABI recognition is conservative: `invoke`/`stdcall`/`fastcall`/`ccall`, external symbol calls, and bracketed indirect calls are treated as ABI-ish or unresolved as appropriate.
- Data references are best-effort identifier matches against known data labels/directives.
