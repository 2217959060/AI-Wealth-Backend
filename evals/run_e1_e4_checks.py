"""
阶段 E1 / E4 轻量回归（不依赖大模型）。

用法:
  python evals/run_e1_e4_checks.py
  docker exec -it ai-wealth-backend python evals/run_e1_e4_checks.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from invest_tools import _shift_month, summarize_spend_by_category
from memory_profile import FIXED_MEMORY_QUERY, load_finance_side_profile

REPORT_DIR = os.path.join(os.path.dirname(__file__), "reports")


class FakeBill:
    def __init__(self, category: str, amount: float, bill_date: str):
        self.category = category
        self.amount = amount
        self.date = bill_date
        self.type = "expense"
        self.is_deleted = 0
        self.user_id = 1


class FakeQuery:
    def __init__(self, bills):
        self._bills = bills

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._bills


class FakeDB:
    def __init__(self, bills):
        self._bills = bills

    def query(self, *args, **kwargs):
        return FakeQuery(self._bills)


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

    def like(self, other):
        return self


class FakeBillModel:
    user_id = _Cmp()
    is_deleted = _Cmp()
    type = _Cmp()
    date = _Cmp()


class FakeModels:
    Bill = FakeBillModel


class FakeDoc:
    def __init__(self, content: str):
        self.page_content = content


class FakeVS:
    def similarity_search(self, query, k=3, filter=None):
        if query == FIXED_MEMORY_QUERY:
            return [FakeDoc("固定侧写：周末冲动消费"), FakeDoc("固定侧写：订阅会员过多")][:k]
        # 问题相关
        if "外卖" in query or "餐饮" in query:
            return [FakeDoc("问题侧写：经常点外卖"), FakeDoc("固定侧写：周末冲动消费")][:k]
        return [FakeDoc(f"问题侧写：与「{query[:12]}」相关的习惯")][:k]


def run_checks() -> list[dict]:
    results = []

    # E1: month shift
    y, m = _shift_month(2026, 8, -2)
    ok_shift = (y, m) == (2026, 6)
    results.append(
        {
            "id": "e1_shift_month",
            "pass": ok_shift,
            "detail": {"got": [y, m], "expect": [2026, 6]},
        }
    )

    # E1: summarize with fake bills
    bills = [
        FakeBill("餐饮", 100, "2026-07-01"),
        FakeBill("餐饮", 50, "2026-08-01"),
        FakeBill("交通", 30, "2026-08-02"),
    ]
    out = summarize_spend_by_category(FakeDB(bills), FakeModels, user_id=1, months=3, top_n=5)
    cats = {c["name"]: c["amount"] for c in out.get("categories", [])}
    ok_sum = (
        out["ok"]
        and not out["empty"]
        and out["tool_trace"]["tool"] == "summarize_spend_by_category"
        and abs(cats.get("餐饮", 0) - 150) < 0.01
        and abs(out["total_expense"] - 180) < 0.01
    )
    results.append(
        {
            "id": "e1_summarize_spend_by_category",
            "pass": ok_sum,
            "detail": {
                "total": out.get("total_expense"),
                "categories": out.get("categories"),
                "tool": out.get("tool_trace", {}).get("tool"),
            },
        }
    )

    # E1: empty
    empty_out = summarize_spend_by_category(FakeDB([]), FakeModels, user_id=1, months=3)
    ok_empty = empty_out["ok"] and empty_out["empty"] and empty_out["total_expense"] == 0
    results.append(
        {
            "id": "e1_summarize_empty",
            "pass": ok_empty,
            "detail": {"empty": empty_out.get("empty"), "total": empty_out.get("total_expense")},
        }
    )

    # E4: dual retrieval + dedupe
    text, trace = load_finance_side_profile(FakeVS(), user_id=1, user_query="我是不是又在乱点外卖")
    ok_mem = (
        "与当前问题相关的习惯侧写" in text
        and "稳定财务痛点侧写" in text
        and "经常点外卖" in text
        and text.count("周末冲动消费") == 1  # 去重：只出现一次
        and len(trace.get("query_hits", [])) >= 1
        and len(trace.get("fixed_hits", [])) >= 1
    )
    results.append(
        {
            "id": "e4_query_and_fixed_memory",
            "pass": ok_mem,
            "detail": {
                "query_hits": trace.get("query_hits"),
                "fixed_hits": trace.get("fixed_hits"),
                "text_preview": text[:120],
            },
        }
    )

    # E4: unavailable store
    text2, trace2 = load_finance_side_profile(None, user_id=1, user_query="test")
    ok_none = text2 == "暂无" and "error" in trace2
    results.append(
        {
            "id": "e4_vectorstore_unavailable",
            "pass": ok_none,
            "detail": trace2,
        }
    )

    return results


def main() -> int:
    os.makedirs(REPORT_DIR, exist_ok=True)
    results = run_checks()
    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "passed": passed,
        "total": total,
        "all_passed": passed == total,
        "results": results,
    }
    out_path = os.path.join(REPORT_DIR, f"e1_e4_{stamp}.json")
    latest = os.path.join(REPORT_DIR, "e1_e4_latest.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(latest, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("=== Stage E1 / E4 Checks ===")
    for r in results:
        print(f"[{'PASS' if r['pass'] else 'FAIL'}] {r['id']}  detail={r['detail']}")
    print(f"\n汇总: {passed}/{total} passed")
    print(f"报告: {out_path}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
