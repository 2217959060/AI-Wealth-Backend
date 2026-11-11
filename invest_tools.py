"""
投资顾问只读工具（阶段 E1）：按品类汇总近 N 月支出。
每次 /ai/invest/chat 确定性调用一次，再注入 Prompt + SSE tool_trace。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from finance_guards import _round_money


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """delta 为负数表示往前推月份。"""
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def summarize_spend_by_category(
    db: Any,
    models: Any,
    user_id: int,
    months: int = 3,
    top_n: int = 8,
) -> dict[str, Any]:
    """
    只读汇总：近 N 个自然月（含本月）的支出分类 TopN。
    返回结构可供 Prompt 与 tool_trace 使用。
    """
    try:
        months = int(months)
    except (TypeError, ValueError):
        months = 3
    months = max(1, min(months, 12))
    try:
        top_n = int(top_n)
    except (TypeError, ValueError):
        top_n = 8
    top_n = max(1, min(top_n, 20))

    today = date.today()
    start_y, start_m = _shift_month(today.year, today.month, -(months - 1))
    start_date = f"{start_y:04d}-{start_m:02d}-01"
    end_date = today.isoformat()

    try:
        bills = (
            db.query(models.Bill)
            .filter(
                models.Bill.user_id == user_id,
                models.Bill.is_deleted == 0,
                models.Bill.type == "expense",
                models.Bill.date >= start_date,
                models.Bill.date <= end_date,
            )
            .all()
        )
    except Exception as e:
        err = f"summarize_spend_by_category 查询失败：{type(e).__name__}"
        print(f"[invest_tool] {err}: {e}")
        return {
            "ok": False,
            "empty": True,
            "months": months,
            "start_date": start_date,
            "end_date": end_date,
            "total_expense": 0.0,
            "categories": [],
            "summary_text": f"🚨 {err}（未生成品类结论）",
            "tool_trace": {
                "round": 1,
                "tool": "summarize_spend_by_category",
                "arguments": {"months": months, "top_n": top_n},
                "ok": False,
                "empty": True,
                "summary": err,
                "error": err,
            },
        }

    cat_sums: dict[str, float] = defaultdict(float)
    for b in bills:
        cat_sums[b.category or "未分类"] += float(b.amount or 0)

    ranked = sorted(cat_sums.items(), key=lambda x: x[1], reverse=True)[:top_n]
    total_expense = _round_money(sum(cat_sums.values()))
    categories = [
        {"name": name, "amount": _round_money(amt)} for name, amt in ranked
    ]
    empty = len(bills) == 0 or total_expense == 0

    lines = [
        f"【工具 summarize_spend_by_category】近 {months} 个月支出品类汇总",
        f"统计区间：{start_date} 至 {end_date}",
        f"支出合计：{total_expense} 元；账单条数：{len(bills)}",
        f"分类 Top{top_n}：",
    ]
    if categories:
        for i, c in enumerate(categories, 1):
            lines.append(f"  {i}. {c['name']}: {c['amount']}元")
    else:
        lines.append("  （该区间无支出记录）")

    summary_text = "\n".join(lines)
    step = {
        "round": 1,
        "tool": "summarize_spend_by_category",
        "arguments": json_args(months, top_n, start_date, end_date),
        "ok": True,
        "empty": empty,
        "summary": summary_text[:240],
        "error": None,
    }
    print(
        f"[invest_tool] summarize_spend_by_category months={months} empty={empty} total={total_expense}"
    )

    return {
        "ok": True,
        "empty": empty,
        "months": months,
        "start_date": start_date,
        "end_date": end_date,
        "total_expense": total_expense,
        "bill_count": len(bills),
        "categories": categories,
        "summary_text": summary_text,
        "tool_trace": step,
    }


def json_args(months: int, top_n: int, start_date: str, end_date: str) -> str:
    import json

    return json.dumps(
        {
            "months": months,
            "top_n": top_n,
            "start_date": start_date,
            "end_date": end_date,
        },
        ensure_ascii=False,
    )
