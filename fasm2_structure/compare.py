from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _by_name(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["name"]: row for row in data.get("functions", [])}


def compare_report_data(before: dict[str, Any], after: dict[str, Any], *, limit: int = 50) -> dict[str, Any]:
    before_funcs = _by_name(before)
    after_funcs = _by_name(after)
    names = sorted(set(before_funcs) | set(after_funcs))
    function_changes = []
    improved = worsened = unchanged = added = removed = 0
    for name in names:
        b = before_funcs.get(name)
        a = after_funcs.get(name)
        if b is None and a is not None:
            added += 1
            delta = a["abi_pressure"]
            status = "added"
        elif a is None and b is not None:
            removed += 1
            delta = -b["abi_pressure"]
            status = "removed"
        else:
            assert a is not None and b is not None
            delta = a["abi_pressure"] - b["abi_pressure"]
            if delta < 0:
                improved += 1
                status = "improved"
            elif delta > 0:
                worsened += 1
                status = "worsened"
            else:
                unchanged += 1
                status = "unchanged"
        function_changes.append(
            {
                "name": name,
                "status": status,
                "before_pressure": None if b is None else b["abi_pressure"],
                "after_pressure": None if a is None else a["abi_pressure"],
                "delta_pressure": delta,
                "before_class": None if b is None else b["pressure_class"],
                "after_class": None if a is None else a["pressure_class"],
                "before_path": None if b is None else b["path"],
                "after_path": None if a is None else a["path"],
                "before_calls": None if b is None else b["total_calls"],
                "after_calls": None if a is None else a["total_calls"],
            }
        )
    total_before_pressure = sum(row["abi_pressure"] for row in before_funcs.values())
    total_after_pressure = sum(row["abi_pressure"] for row in after_funcs.values())
    ranked = sorted(
        (r for r in function_changes if r["delta_pressure"] != 0 or r["status"] in {"added", "removed"}),
        key=lambda r: (abs(r["delta_pressure"]), r["name"]),
        reverse=True,
    )
    return {
        "summary": {
            "before_functions": before.get("summary", {}).get("functions", len(before_funcs)),
            "after_functions": after.get("summary", {}).get("functions", len(after_funcs)),
            "before_total_abi_pressure": total_before_pressure,
            "after_total_abi_pressure": total_after_pressure,
            "delta_total_abi_pressure": total_after_pressure - total_before_pressure,
            "improved_functions": improved,
            "worsened_functions": worsened,
            "unchanged_functions": unchanged,
            "added_functions": added,
            "removed_functions": removed,
        },
        "largest_changes": ranked[:limit],
        "improvements": [r for r in ranked if r["status"] == "improved"][:limit],
        "regressions": [r for r in ranked if r["status"] == "worsened"][:limit],
        "added": [r for r in ranked if r["status"] == "added"][:limit],
        "removed": [r for r in ranked if r["status"] == "removed"][:limit],
    }


def comparison_markdown(comparison: dict[str, Any], title: str = "Refactor comparison") -> str:
    s = comparison["summary"]
    lines = [f"# {title}", ""]
    lines.append(
        f"Total ABI pressure: {s['before_total_abi_pressure']} -> {s['after_total_abi_pressure']} "
        f"(delta {s['delta_total_abi_pressure']:+})."
    )
    lines.append(
        f"Functions: {s['before_functions']} -> {s['after_functions']} | "
        f"improved {s['improved_functions']}, worsened {s['worsened_functions']}, "
        f"unchanged {s['unchanged_functions']}, added {s['added_functions']}, removed {s['removed_functions']}."
    )
    lines.append("")
    lines.append("## Largest pressure changes")
    if not comparison["largest_changes"]:
        lines.append("- No function pressure changes detected.")
    for row in comparison["largest_changes"][:25]:
        lines.append(
            f"- {row['delta_pressure']:+}: `{row['name']}` "
            f"{row['before_pressure']} -> {row['after_pressure']} "
            f"({row['before_class']} -> {row['after_class']})"
        )
    lines.append("")
    lines.append("## Regression gate")
    if comparison["regressions"]:
        lines.append("- Review pressure regressions before accepting the refactor.")
    else:
        lines.append("- No ABI-pressure regressions detected by this heuristic.")
    lines.append("")
    return "\n".join(lines)


def write_comparison(out_dir: str | Path, before: dict[str, Any], after: dict[str, Any], *, limit: int = 50) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    comparison = compare_report_data(before, after, limit=limit)
    json_path = out / "refactor-compare.json"
    md_path = out / "refactor-compare.md"
    json_path.write_text(json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(comparison_markdown(comparison) + "\n", encoding="utf-8")
    return {"compare_json": json_path, "compare_md": md_path}


def load_report_data(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
