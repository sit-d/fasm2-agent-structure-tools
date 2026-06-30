from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .analysis import StructureModel
from .report import build_report_data


@dataclass(frozen=True)
class AdviceThresholds:
    high_pressure: int = 20
    medium_pressure: int = 10
    high_fanout: int = 20
    high_internal_fanout: int = 8


def _callers_and_callees(data: dict[str, Any]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    callers: dict[str, set[str]] = {}
    callees: dict[str, set[str]] = {}
    function_names = {f["name"] for f in data["functions"]}
    for edge in data["edges"]:
        if edge["source"] in function_names and edge["target"] in function_names:
            callees.setdefault(edge["source"], set()).add(edge["target"])
            callers.setdefault(edge["target"], set()).add(edge["source"])
    return callers, callees


def pressure_bucket(row: dict[str, Any], thresholds: AdviceThresholds) -> str:
    if row["abi_pressure"] == 0:
        return "pure-leaf"
    if row["abi_pressure"] >= thresholds.high_pressure:
        return "high-pressure"
    if row["abi_pressure"] >= thresholds.medium_pressure:
        return "medium-pressure"
    return "low-pressure"


def action_for(row: dict[str, Any], caller_count: int, callee_count: int, thresholds: AdviceThresholds) -> str:
    cls = row["pressure_class"]
    if cls == "pure_leaf":
        if caller_count >= 5:
            return "Keep as stable leaf utility; prefer reuse rather than rewriting."
        return "Low-risk leaf; consider inlining/macro extraction only if call overhead matters."
    if cls == "tail_abi":
        return "Consider representing as a thin wrapper/macro or isolating as a named ABI boundary."
    if cls == "abi_boundary":
        if row["abi_calls"] >= thresholds.high_pressure:
            return "Split orchestration from repeated ABI boundary calls; group API interactions behind a narrower adapter."
        return "Keep ABI boundary explicit; verify it does not leak into lower utility layers."
    if row["parameter_uses_after_abi_call"] >= thresholds.medium_pressure:
        return "Prioritize refactor: preserve parameters in explicit locals/state object or split pre/post-ABI phases."
    if callee_count >= thresholds.high_internal_fanout:
        return "Split coordination fan-out from ABI state handling; extract independent pure helpers first."
    return "Inspect manually: ABI state survives across calls, so frame/register choreography may hide structure issues."


def build_refactor_advice_from_data(data: dict[str, Any], thresholds: AdviceThresholds | None = None) -> dict[str, Any]:
    thresholds = thresholds or AdviceThresholds()
    callers, callees = _callers_and_callees(data)
    functions = data["functions"]

    ranked = []
    for row in functions:
        caller_count = len(callers.get(row["name"], set()))
        callee_count = len(callees.get(row["name"], set()))
        score = row["abi_pressure"] + max(0, row["total_calls"] - thresholds.high_fanout) + max(0, caller_count - 5)
        reasons = []
        if row["abi_pressure"] >= thresholds.high_pressure:
            reasons.append(f"high ABI pressure {row['abi_pressure']}")
        elif row["abi_pressure"] >= thresholds.medium_pressure:
            reasons.append(f"medium ABI pressure {row['abi_pressure']}")
        if row["parameter_uses_after_abi_call"]:
            reasons.append(f"{row['parameter_uses_after_abi_call']} parameter-use evidence after ABI calls")
        if row["total_calls"] >= thresholds.high_fanout:
            reasons.append(f"wide fan-out {row['total_calls']} calls")
        if caller_count >= 5:
            reasons.append(f"fan-in {caller_count} callers")
        if row["layer"] == 0 and row["abi_pressure"] >= thresholds.medium_pressure:
            reasons.append("high pressure in leaf dependency layer")
        if not reasons and row["abi_pressure"] == 0:
            reasons.append("pure leaf")
        ranked.append(
            {
                **row,
                "caller_count": caller_count,
                "callee_count": callee_count,
                "refactor_score": score,
                "bucket": pressure_bucket(row, thresholds),
                "reasons": reasons,
                "suggested_action": action_for(row, caller_count, callee_count, thresholds),
            }
        )

    ranked.sort(key=lambda r: (-r["refactor_score"], -r["abi_pressure"], r["name"]))
    pressure_targets = [r for r in ranked if r["abi_pressure"] >= thresholds.medium_pressure]
    pure_utilities = sorted(
        [r for r in ranked if r["abi_pressure"] == 0],
        key=lambda r: (-r["caller_count"], -r["total_calls"], r["name"]),
    )

    module_hotspots = []
    for module in data["module_graph"]["nodes"]:
        module_rows = [r for r in ranked if r["module"] == module["id"]]
        if not module_rows:
            continue
        total_pressure = sum(r["abi_pressure"] for r in module_rows)
        high_count = sum(1 for r in module_rows if r["abi_pressure"] >= thresholds.medium_pressure)
        module_hotspots.append(
            {
                "module": module["id"],
                "functions": len(module_rows),
                "total_abi_pressure": total_pressure,
                "max_abi_pressure": max(r["abi_pressure"] for r in module_rows),
                "high_or_medium_pressure_functions": high_count,
            }
        )
    module_hotspots.sort(key=lambda m: (-m["total_abi_pressure"], -m["max_abi_pressure"], m["module"]))

    return {
        "summary": data["summary"],
        "thresholds": thresholds.__dict__,
        "pressure_targets": pressure_targets[:50],
        "pure_utilities": pure_utilities[:50],
        "module_hotspots": module_hotspots[:25],
        "structure_smells": data["smells"][:100],
        "agent_workflow": [
            "Start with the highest refactor_score pressure target that is inside the intended scope.",
            "Open the HTML report and inspect the function neighborhood at depth 1, then depth 2.",
            "If pressure_class is abi_state_pressure, split pre-ABI argument preparation, ABI boundary calls, and post-ABI state use.",
            "If a high-pressure routine is in layer 0, avoid letting it become a reusable low-level dependency; move ABI interaction upward or behind an adapter.",
            "Use pure_utilities as safe extraction/reuse candidates; keep them independent of ABI boundaries.",
            "After each code refactor, regenerate this advice and verify the pressure target moved down or became better isolated.",
        ],
    }


def build_refactor_advice(model: StructureModel, thresholds: AdviceThresholds | None = None) -> dict[str, Any]:
    return build_refactor_advice_from_data(build_report_data(model), thresholds)


def advice_markdown(advice: dict[str, Any], title: str = "Agentic refactor advice") -> str:
    lines = [f"# {title}", ""]
    s = advice["summary"]
    lines.append(
        f"Summary: {s['functions']} functions, {s['edges']} edges, {s['sccs']} SCCs, "
        f"{s['layers']} layers, max ABI pressure {s['max_abi_pressure']}, {s['pure_leaves']} pure leaves."
    )
    lines.append("")
    lines.append("## Agent workflow")
    for step in advice["agent_workflow"]:
        lines.append(f"- {step}")
    lines.append("")
    lines.append("## Top refactor targets")
    for row in advice["pressure_targets"][:20]:
        lines.append(
            f"- score={row['refactor_score']} pressure={row['abi_pressure']} class={row['pressure_class']} "
            f"layer={row['layer']} calls={row['total_calls']} callers={row['caller_count']} "
            f"`{row['name']}` ({row['path']}:{row['line']})"
        )
        lines.append(f"  - reasons: {', '.join(row['reasons'])}")
        lines.append(f"  - action: {row['suggested_action']}")
    lines.append("")
    lines.append("## Module hotspots")
    for module in advice["module_hotspots"][:15]:
        lines.append(
            f"- `{module['module']}`: total pressure {module['total_abi_pressure']}, "
            f"max {module['max_abi_pressure']}, medium/high funcs {module['high_or_medium_pressure_functions']}/{module['functions']}"
        )
    lines.append("")
    lines.append("## Reusable pure utilities")
    for row in advice["pure_utilities"][:20]:
        lines.append(
            f"- callers={row['caller_count']} calls={row['total_calls']} `{row['name']}` ({row['path']}:{row['line']})"
        )
    lines.append("")
    return "\n".join(lines)


def write_refactor_advice_from_data(out_dir: str | Path, data: dict[str, Any], thresholds: AdviceThresholds | None = None) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    advice = build_refactor_advice_from_data(data, thresholds)
    json_path = out / "refactor-advice.json"
    md_path = out / "refactor-advice.md"
    json_path.write_text(json.dumps(advice, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(advice_markdown(advice) + "\n", encoding="utf-8")
    return {"refactor_advice_json": json_path, "refactor_advice_md": md_path}


def write_refactor_advice(out_dir: str | Path, model: StructureModel) -> dict[str, Path]:
    return write_refactor_advice_from_data(out_dir, build_report_data(model))
