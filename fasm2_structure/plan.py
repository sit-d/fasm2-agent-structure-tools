from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .refactor import AdviceFilters, AdviceThresholds, build_refactor_advice_from_data


def _task_scope(row: dict[str, Any]) -> str:
    return f"{row['path']}:{row['line']} {row['name']}"


def _expected_outcome(row: dict[str, Any]) -> str:
    cls = row["pressure_class"]
    if cls == "abi_state_pressure":
        return "ABI state use is isolated: argument preparation, ABI boundary, and post-call state handling are explicit and easier to review."
    if cls == "abi_boundary":
        return "ABI boundary calls are grouped behind a narrower adapter or orchestration routine, without leaking into lower-level helpers."
    if cls == "tail_abi":
        return "Thin wrapper/tail-call intent is documented or represented in a smaller wrapper/macro-like shape."
    return "Pure utility remains independent and reusable."


def _refactor_steps(row: dict[str, Any]) -> list[str]:
    steps = [
        f"Open the target around `{_task_scope(row)}` and read the complete routine before editing.",
        "Open `report.html`, focus this function, and inspect depth 1 then depth 2 neighborhoods.",
    ]
    if row["pressure_class"] == "abi_state_pressure":
        steps.extend(
            [
                "Mark incoming parameters/register state that are used after ABI calls.",
                "Split pre-ABI preparation from ABI invocation and post-ABI state use where source layout permits.",
                "Prefer explicit locals/state names over hidden register lifetime coupling.",
            ]
        )
    elif row["pressure_class"] == "abi_boundary":
        steps.extend(
            [
                "Group repeated ABI calls into a named boundary/adaptor when it reduces orchestration fan-out.",
                "Keep lower-level pure helpers free of direct ABI interaction.",
            ]
        )
    else:
        steps.append("Preserve the routine shape unless the caller graph shows a clear extraction/reuse opportunity.")
    steps.extend(
        [
            "Regenerate `--report --advice --plan` after the edit.",
            "Compare ABI pressure, call fan-out, and module hotspot movement before/after.",
        ]
    )
    return steps


def build_refactor_plan_from_advice(advice: dict[str, Any], *, limit: int = 8) -> dict[str, Any]:
    tasks = []
    for index, row in enumerate(advice["pressure_targets"][:limit], start=1):
        tasks.append(
            {
                "id": f"task-{index:02d}",
                "title": f"Refactor pressure target `{row['name']}`",
                "scope": _task_scope(row),
                "refactor_score": row["refactor_score"],
                "abi_pressure": row["abi_pressure"],
                "pressure_class": row["pressure_class"],
                "reasons": row["reasons"],
                "suggested_action": row["suggested_action"],
                "expected_outcome": _expected_outcome(row),
                "steps": _refactor_steps(row),
                "verification": [
                    "Run the target project's existing build/tests or at minimum its assembler/build smoke path.",
                    "Run this tool again with `--report --advice --plan` into a fresh output directory.",
                    "Confirm the edited routine's pressure or fan-out decreased, or that high pressure moved behind a clearer boundary.",
                ],
            }
        )
    return {
        "summary": advice["summary"],
        "tasks": tasks,
        "notes": [
            "Treat this as a review/refactor queue, not an automatic patch recipe.",
            "Skip generated examples or out-of-scope demo code unless that is the intended target.",
            "Prefer one pressure target per commit so before/after analysis remains attributable.",
            "Do not change semantics just to lower ABI pressure; the metric is a navigation signal, not a correctness oracle.",
        ],
    }


def build_refactor_plan_from_data(
    data: dict[str, Any],
    *,
    limit: int = 8,
    thresholds: AdviceThresholds | None = None,
    filters: AdviceFilters | None = None,
) -> dict[str, Any]:
    return build_refactor_plan_from_advice(build_refactor_advice_from_data(data, thresholds, filters), limit=limit)


def refactor_plan_markdown(plan: dict[str, Any], title: str = "Agentic refactor plan") -> str:
    lines = [f"# {title}", ""]
    s = plan["summary"]
    lines.append(
        f"Summary: {s['functions']} functions, {s['edges']} edges, {s['sccs']} SCCs, "
        f"{s['layers']} layers, max ABI pressure {s['max_abi_pressure']}, {s['pure_leaves']} pure leaves."
    )
    lines.append("")
    lines.append("## How to use this plan")
    for note in plan["notes"]:
        lines.append(f"- {note}")
    lines.append("")
    lines.append("## Tasks")
    for task in plan["tasks"]:
        lines.append("")
        lines.append(f"### {task['id']}: {task['title']}")
        lines.append(f"- Scope: {task['scope']}")
        lines.append(f"- Score: {task['refactor_score']}")
        lines.append(f"- ABI pressure: {task['abi_pressure']} ({task['pressure_class']})")
        lines.append(f"- Reasons: {', '.join(task['reasons'])}")
        lines.append(f"- Suggested action: {task['suggested_action']}")
        lines.append(f"- Expected outcome: {task['expected_outcome']}")
        lines.append("- Steps:")
        for step in task["steps"]:
            lines.append(f"  - {step}")
        lines.append("- Verification:")
        for item in task["verification"]:
            lines.append(f"  - {item}")
    lines.append("")
    return "\n".join(lines)


def write_refactor_plan_from_data(
    out_dir: str | Path,
    data: dict[str, Any],
    *,
    limit: int = 8,
    thresholds: AdviceThresholds | None = None,
    filters: AdviceFilters | None = None,
) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    plan = build_refactor_plan_from_data(data, limit=limit, thresholds=thresholds, filters=filters)
    json_path = out / "refactor-plan.json"
    md_path = out / "refactor-plan.md"
    json_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(refactor_plan_markdown(plan) + "\n", encoding="utf-8")
    return {"refactor_plan_json": json_path, "refactor_plan_md": md_path}
