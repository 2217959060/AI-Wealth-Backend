"""
理财管家阶段 C/D/F/G 回归：闸门 + 双工具编排 + 失败重规划 + 终止条件，确定性断言（不依赖大模型，可一键跑）。

用法（项目根目录）:
  python evals/run_finance_checks.py
  docker exec -it ai-wealth-backend python evals/run_finance_checks.py
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from finance_guards import (
    apply_output_guards,
    build_tool_result_from_bills,
    failure_tool_result,
    has_echarts_block,
    normalize_date_range,
    parse_tool_arguments,
)
from finance_agent import (
    FINANCE_TOOLS,
    MAX_FAILURE_REPLANS,
    MAX_TOOL_ROUNDS,
    merge_tool_results,
    run_finance_tool_loop,
)

REPORT_DIR = os.path.join(os.path.dirname(__file__), "reports")
CASES_PATH = os.path.join(os.path.dirname(__file__), "cases_finance.jsonl")

# Agent 编排行为用例（与「输出闸门 / 参数校验」分开统计，便于单独看编排回归）
ORCHESTRATION_IDS = {
    "fin_dual_tools_and_max_rounds",
    "fin_two_step_merge_chart_guard",
    "fin_replan_recovers",
    "fin_replan_still_fails_degrades",
    "fin_max_rounds_still_wants_tool",
    "fin_two_rounds_normal_termination",
}


@dataclass
class FakeBill:
    type: str
    amount: float
    date: str
    category: str = "餐饮"


def _chart_block(income_data, expense_data, dates) -> str:
    payload = {
        "title": {"text": "测试图"},
        "xAxis": {"type": "category", "data": dates},
        "yAxis": {"type": "value"},
        "series": [
            {"name": "收入", "type": "bar", "data": income_data},
            {"name": "支出", "type": "bar", "data": expense_data},
        ],
    }
    return "分析文字\n\n```echarts\n" + json.dumps(payload, ensure_ascii=False) + "\n```\n"


class _FakeFn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, call_id, name, arguments):
        self.id = call_id
        self.function = _FakeFn(name, arguments)


class _FakeResponse:
    def __init__(self, tool_calls):
        message = type("Msg", (), {"role": "assistant", "content": "", "tool_calls": tool_calls})()
        self.choices = [type("Choice", (), {"message": message})()]


class _ScriptedClient:
    """按脚本返回 tool_calls，模拟「非法参数 → 修正参数重试」，不依赖大模型。"""

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0
        self.last_messages = None
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.calls += 1
        self.last_messages = kwargs.get("messages")
        item = self._script.pop(0) if self._script else []
        return _FakeResponse([_FakeToolCall(*t) for t in item])


class _Cmp:
    def __eq__(self, other):
        return self

    def __ge__(self, other):
        return self

    def __le__(self, other):
        return self

    def __gt__(self, other):
        return self

    def __lt__(self, other):
        return self


class _FakeBillModel:
    user_id = _Cmp()
    is_deleted = _Cmp()
    type = _Cmp()
    date = _Cmp()
    category = _Cmp()


class _FakeModels:
    Bill = _FakeBillModel


class _FakeQuery:
    def __init__(self, bills):
        self._bills = bills

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._bills


class _FakeDB:
    def __init__(self, bills):
        self._bills = bills

    def query(self, *args, **kwargs):
        return _FakeQuery(self._bills)


def _run_loop(script):
    client = _ScriptedClient(script)
    result, trace, used = run_finance_tool_loop(
        client,
        db=_FakeDB([FakeBill("expense", 100.0, "2026-05-01")]),
        models=_FakeModels,
        user_id=1,
        planner_messages=[{"role": "user", "content": "查本月支出"}],
    )
    return client, result, trace, used


def run_checks() -> list[dict]:
    results: list[dict] = []

    # --- fin_empty_no_chart ---
    empty_tool = build_tool_result_from_bills([], "2099-01-01", "2099-01-31", "all")
    hallucinated = _chart_block([9999], [8888], ["2099-01-01"])
    out, ev = apply_output_guards(hallucinated, empty_tool)
    ok = empty_tool.empty and not has_echarts_block(out) and any(
        "empty" in e or "stripped" in e for e in ev
    )
    results.append(
        {
            "id": "fin_empty_no_chart",
            "pass": ok,
            "detail": {"empty": empty_tool.empty, "events": ev, "has_echarts": has_echarts_block(out)},
        }
    )

    # --- fin_valid_chart_kept ---
    bills = [
        FakeBill("income", 100.0, "2026-06-01"),
        FakeBill("expense", 50.0, "2026-06-01"),
        FakeBill("expense", 30.0, "2026-06-02"),
    ]
    tool_ok = build_tool_result_from_bills(bills, "2026-06-01", "2026-06-30", "all")
    good = _chart_block([100, 0], [50, 30], ["2026-06-01", "2026-06-02"])
    out2, ev2 = apply_output_guards(good, tool_ok)
    ok2 = (not tool_ok.empty) and has_echarts_block(out2) and "chart_validation_passed" in ev2
    results.append(
        {
            "id": "fin_valid_chart_kept",
            "pass": ok2,
            "detail": {
                "totals": [tool_ok.total_income, tool_ok.total_expense],
                "events": ev2,
                "has_echarts": has_echarts_block(out2),
            },
        }
    )

    # --- fin_bad_chart_stripped ---
    bad = _chart_block([100, 0], [50, 99999], ["2026-06-01", "2026-06-02"])
    out3, ev3 = apply_output_guards(bad, tool_ok)
    ok3 = not has_echarts_block(out3) and any("chart_validation_failed" in e for e in ev3)
    results.append(
        {
            "id": "fin_bad_chart_stripped",
            "pass": ok3,
            "detail": {"events": ev3, "has_echarts": has_echarts_block(out3)},
        }
    )

    # --- fin_bad_json_args ---
    args, err = parse_tool_arguments("{start_date: bad")
    ok4 = args is None and err is not None
    fail_res = failure_tool_result(err or "parse fail")
    out4, ev4 = apply_output_guards(_chart_block([1], [2], ["x"]), fail_res)
    ok4 = ok4 and not fail_res.ok and not has_echarts_block(out4)
    results.append(
        {
            "id": "fin_bad_json_args",
            "pass": ok4,
            "detail": {"parse_err": err, "events": ev4},
        }
    )

    # --- fin_bad_dates ---
    s, e, date_err, notes = normalize_date_range("2026-13-99", "2026-01-01")
    ok5 = s is None and date_err is not None
    results.append(
        {
            "id": "fin_bad_dates",
            "pass": ok5,
            "detail": {"error": date_err, "notes": notes},
        }
    )

    # --- fin_date_swap ---
    s2, e2, err2, notes2 = normalize_date_range("2026-06-30", "2026-06-01")
    ok6 = err2 is None and s2 == "2026-06-01" and e2 == "2026-06-30" and "date_range_swapped" in notes2
    results.append(
        {
            "id": "fin_date_swap",
            "pass": ok6,
            "detail": {"start": s2, "end": e2, "notes": notes2},
        }
    )

    # --- fin_current_tool_only ---
    # 当次 tool 只有 100/50；历史旧金额 7777 不应通过
    stale = _chart_block([7777], [50], ["2026-06-01"])
    out7, ev7 = apply_output_guards(stale, tool_ok)
    ok7 = not has_echarts_block(out7) and any("value_not_in_tool" in e for e in ev7)
    results.append(
        {
            "id": "fin_current_tool_only",
            "pass": ok7,
            "detail": {"events": ev7, "allowed_sample": sorted(list(tool_ok.allowed_values))[:8]},
        }
    )

    # --- Stage D: dual tools + merge + max rounds ---
    tool_names = {t["function"]["name"] for t in FINANCE_TOOLS}
    ok_d1 = tool_names == {"query_bills", "aggregate_stats"} and MAX_TOOL_ROUNDS == 2
    results.append(
        {
            "id": "fin_dual_tools_and_max_rounds",
            "pass": ok_d1,
            "detail": {"tools": sorted(tool_names), "max_tool_rounds": MAX_TOOL_ROUNDS},
        }
    )

    month_a = build_tool_result_from_bills(
        [FakeBill("expense", 40.0, "2026-05-01")], "2026-05-01", "2026-05-31", "expense"
    )
    month_b = build_tool_result_from_bills(
        [FakeBill("expense", 60.0, "2026-06-01")], "2026-06-01", "2026-06-30", "expense"
    )
    merged = merge_tool_results([month_a, month_b])
    # 用「历史旧金额」测合并后的闸门仍只认当次 merged allowed
    compare_chart = _chart_block([0], [40, 60], ["2026-05", "2026-06"])
    # 简化：单 series 长度需对齐 —— 用两个点
    compare_chart = (
        "对比文字\n\n```echarts\n"
        + json.dumps(
            {
                "xAxis": {"type": "category", "data": ["5月", "6月"]},
                "series": [{"name": "支出", "type": "bar", "data": [40.0, 60.0]}],
            },
            ensure_ascii=False,
        )
        + "\n```\n"
    )
    out_m, ev_m = apply_output_guards(compare_chart, merged)
    bad_m = (
        "对比文字\n\n```echarts\n"
        + json.dumps(
            {
                "xAxis": {"type": "category", "data": ["5月", "6月"]},
                "series": [{"name": "支出", "type": "bar", "data": [40.0, 9999.0]}],
            },
            ensure_ascii=False,
        )
        + "\n```\n"
    )
    out_bad, ev_bad = apply_output_guards(bad_m, merged)
    ok_d2 = (
        "merged_multi_tool" in merged.notes
        and has_echarts_block(out_m)
        and "chart_validation_passed" in ev_m
        and not has_echarts_block(out_bad)
    )
    results.append(
        {
            "id": "fin_two_step_merge_chart_guard",
            "pass": ok_d2,
            "detail": {
                "merged_expense": merged.total_expense,
                "events_ok": ev_m,
                "events_bad": ev_bad,
            },
        }
    )

    # --- Stage F: 工具失败重规划（确定性 Agent 行为回归） ---
    bad_args = '{"start_date":"不是日期","end_date":"2026-05-31","query_type":"expense"}'
    good_args = '{"start_date":"2026-05-01","end_date":"2026-05-31","query_type":"expense"}'

    client_r, result_r, trace_r, used_r = _run_loop(
        [[("call-1", "aggregate_stats", bad_args)], [("call-2", "aggregate_stats", good_args)]]
    )
    replan_hint_seen = any(
        "重新调用工具" in str(m.get("content") or "")
        for m in (client_r.last_messages or [])
        if m.get("role") == "tool"
    )
    ok_f1 = (
        MAX_FAILURE_REPLANS == 1
        and client_r.calls == 2  # 重试复用下一轮，未超出步数预算
        and used_r
        and result_r is not None
        and result_r.ok
        and trace_r[0].get("replan") is True
        and trace_r[-1].get("recovered") is True
        and replan_hint_seen  # 失败语义已改写为重规划指令
    )
    results.append(
        {
            "id": "fin_replan_recovers",
            "pass": ok_f1,
            "detail": {
                "llm_calls": client_r.calls,
                "result_ok": bool(result_r and result_r.ok),
                "trace": trace_r,
            },
        }
    )

    client_f, result_f, trace_f, used_f = _run_loop(
        [[("call-1", "aggregate_stats", bad_args)], [("call-2", "aggregate_stats", bad_args)]]
    )
    ok_f2 = (
        client_f.calls == 2
        and used_f
        and result_f is not None
        and not result_f.ok
        and bool(result_f.error_message)
        and len([s for s in trace_f if s.get("replan")]) == 1
        and result_f.db_result_str.count("🚨") == 1  # 降级语义只保留一次，不重复错误块
    )
    results.append(
        {
            "id": "fin_replan_still_fails_degrades",
            "pass": ok_f2,
            "detail": {
                "llm_calls": client_f.calls,
                "result_ok": bool(result_f and result_f.ok),
                "error": result_f.error_message if result_f else None,
                "trace": trace_f,
            },
        }
    )

    # --- Stage G: 编排终止条件（确定性 Agent 行为回归） ---
    may_args = '{"start_date":"2026-05-01","end_date":"2026-05-31","query_type":"expense"}'
    june_args = '{"start_date":"2026-06-01","end_date":"2026-06-30","query_type":"expense"}'

    # 最后一轮模型仍要工具：执行完本轮即停，不得再发起第 3 次 LLM 调用
    client_m, result_m, trace_m, used_m = _run_loop(
        [
            [("call-1", "aggregate_stats", may_args)],
            [("call-2", "aggregate_stats", june_args)],
        ]
    )
    ok_g1 = (
        client_m.calls == 2
        and used_m
        and result_m is not None
        and result_m.ok
        and len(trace_m) == 2
        and all(s.get("replan") is False for s in trace_m)
        and "merged_multi_tool" in result_m.notes
    )
    results.append(
        {
            "id": "fin_max_rounds_still_wants_tool",
            "pass": ok_g1,
            "detail": {
                "llm_calls": client_m.calls,
                "trace_len": len(trace_m),
                "merged": "merged_multi_tool" in (result_m.notes if result_m else []),
            },
        }
    )

    # 第 2 轮模型不再调工具：提前终止，保留已有结果
    client_t, result_t, trace_t, used_t = _run_loop(
        [[("call-1", "aggregate_stats", may_args)], []]
    )
    ok_g2 = (
        client_t.calls == 2
        and used_t
        and result_t is not None
        and result_t.ok
        and len(trace_t) == 1
        and "merged_multi_tool" not in result_t.notes
    )
    results.append(
        {
            "id": "fin_two_rounds_normal_termination",
            "pass": ok_g2,
            "detail": {
                "llm_calls": client_t.calls,
                "trace_len": len(trace_t),
                "result_ok": bool(result_t and result_t.ok),
            },
        }
    )

    return results


def main() -> int:
    os.makedirs(REPORT_DIR, exist_ok=True)
    results = run_checks()
    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    orchestration = [r for r in results if r["id"] in ORCHESTRATION_IDS]
    orch_passed = sum(1 for r in orchestration if r["pass"])
    orch_total = len(orchestration)
    guard_total = total - orch_total
    guard_passed = passed - orch_passed
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "passed": passed,
        "total": total,
        "all_passed": passed == total,
        "orchestration_regression": {
            "passed": orch_passed,
            "total": orch_total,
            "all_passed": orch_passed == orch_total,
            "case_ids": [r["id"] for r in orchestration],
        },
        "guards_validation": {
            "passed": guard_passed,
            "total": guard_total,
            "all_passed": guard_passed == guard_total,
        },
        "results": results,
        "cases_file": CASES_PATH,
    }
    out_path = os.path.join(REPORT_DIR, f"finance_guards_{stamp}.json")
    latest_path = os.path.join(REPORT_DIR, "finance_guards_latest.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("=== Finance Guards + Agent Regression (Stage C/D/F/G) ===")
    for r in results:
        mark = "PASS" if r["pass"] else "FAIL"
        print(f"[{mark}] {r['id']}  detail={r['detail']}")
    print(f"\n汇总: {passed}/{total} passed")
    print(
        f"编排行为回归: {orch_passed}/{orch_total} passed | "
        f"闸门/参数校验: {guard_passed}/{guard_total} passed"
    )
    print(f"报告: {out_path}")
    print(f"最新: {latest_path}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
