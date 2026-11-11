"""
理赔 grounding 闸门确定性回归（不调 Embedding / LLM）。

覆盖：
- 有召回 → 允许生成
- 空召回 → 硬拒答 + policy_hard_refuse_empty
- 距离门槛滤光 → 硬拒答 + policy_hard_refuse_filtered

用法（项目根目录）:
  python evals/run_policy_guards.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from policy_rag import (
    HARD_REFUSE_REPLY,
    REFUSE_PHRASE,
    assess_policy_grounding,
    filter_sources_by_distance,
)

REPORT_DIR = os.path.join(os.path.dirname(__file__), "reports")


def _src(score: float | None, content: str = "条款片段") -> dict:
    return {
        "index": 1,
        "snippet": content[:40],
        "page": 1,
        "score": score,
        "content": content,
    }


def main() -> int:
    results: list[dict] = []

    # 1) 有召回
    d1 = assess_policy_grounding([_src(0.8)], had_raw_hits=True)
    ok1 = d1.allow_generate and d1.reason == "ok" and not d1.guards
    results.append({"id": "policy_allow_when_hits", "ok": ok1, "detail": d1.reason})

    # 2) 空召回
    d2 = assess_policy_grounding([], had_raw_hits=False)
    ok2 = (
        (not d2.allow_generate)
        and d2.reason == "empty_retrieval"
        and "policy_hard_refuse_empty" in d2.guards
        and REFUSE_PHRASE in HARD_REFUSE_REPLY
    )
    results.append({"id": "policy_hard_refuse_empty", "ok": ok2, "detail": d2.guards})

    # 3) 距离过滤后为空
    raw = [_src(2.5), _src(3.0)]
    filtered = filter_sources_by_distance(raw, max_distance=1.2)
    d3 = assess_policy_grounding(filtered, had_raw_hits=True)
    ok3 = (
        len(filtered) == 0
        and (not d3.allow_generate)
        and d3.reason == "distance_filtered"
        and "policy_hard_refuse_filtered" in d3.guards
    )
    results.append(
        {
            "id": "policy_hard_refuse_filtered",
            "ok": ok3,
            "detail": {"kept": len(filtered), "reason": d3.reason},
        }
    )

    # 4) 距离过滤保留近邻
    raw4 = [_src(0.9), _src(2.0)]
    kept4 = filter_sources_by_distance(raw4, max_distance=1.2)
    d4 = assess_policy_grounding(kept4, had_raw_hits=True)
    ok4 = len(kept4) == 1 and d4.allow_generate and kept4[0]["index"] == 1
    results.append(
        {"id": "policy_keep_near_neighbors", "ok": ok4, "detail": {"kept": len(kept4)}}
    )

    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    report = {
        "stamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "passed": passed,
        "total": total,
        "results": results,
    }

    os.makedirs(REPORT_DIR, exist_ok=True)
    out = os.path.join(REPORT_DIR, f"policy_guards_{report['stamp']}.json")
    latest = os.path.join(REPORT_DIR, "policy_guards_latest.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(latest, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    for r in results:
        mark = "✅" if r["ok"] else "❌"
        print(f"{mark} {r['id']}: {r['detail']}")
    print(f"\n{passed}/{total} passed → {latest}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
