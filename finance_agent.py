"""
理财管家薄编排（阶段 D）：
- 双工具 query_bills / aggregate_stats
- max_tool_rounds 有限步循环 + tool_trace
- 工具失败走阶段 C 的 failure / date 语义
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Optional

from finance_guards import (
    ToolQueryResult,
    _round_money,
    build_allowed_values,
    build_tool_result_from_bills,
    failure_tool_result,
    format_db_result_str,
    normalize_date_range,
    parse_tool_arguments,
)

logger = logging.getLogger("finance_agent")

from llm_config import CHAT_MODEL

MAX_TOOL_ROUNDS = 2
# 工具失败时允许「换参数重试」的次数；复用同一轮次预算，不额外增加 LLM 调用
MAX_FAILURE_REPLANS = 1
FINANCE_CHAT_MODEL = CHAT_MODEL

REPLAN_TOOL_MESSAGE = (
    "🚨 上一次工具调用未成功：{reason}\n"
    "请根据错误【修正参数后重新调用工具】，不要直接向用户解释失败，"
    "不要编造任何金额；若确实无法修正，请用纯文本说明原因。"
)

FINANCE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_bills",
            "description": (
                "按日期区间查询账单明细的日汇总（可筛选收入/支出/分类）。"
                "适合看流水、按日趋势、某分类花了哪些天。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "起始日期 YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
                    "query_type": {
                        "type": "string",
                        "enum": ["expense", "income", "all"],
                        "description": "expense/income/all",
                    },
                    "category": {
                        "type": "string",
                        "description": "可选。按分类过滤，如：餐饮、交通",
                    },
                },
                "required": ["start_date", "end_date", "query_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate_stats",
            "description": (
                "按日期区间汇总统计：总收入、总支出、结余、分类 TopN。"
                "适合对比两个月、看分类占比；对比时应对每个时间段各调用一次。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "起始日期 YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
                    "query_type": {
                        "type": "string",
                        "enum": ["expense", "income", "all"],
                        "description": "expense/income/all",
                    },
                    "category": {
                        "type": "string",
                        "description": "可选。只统计某一分类",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "分类 TopN，默认 5",
                    },
                },
                "required": ["start_date", "end_date", "query_type"],
            },
        },
    },
]


def build_planner_system_prompt(today_str: str, long_term_memory_str: str) -> str:
    return f"""你是财务管家的【薄编排 Planner】。今天是 {today_str}。
你可以使用工具查询真实账单，禁止编造金额。

【用户财务侧写】
{long_term_memory_str}

【可用工具】
1. query_bills：查区间内按日汇总流水（可加 category）
2. aggregate_stats：查区间汇总 + 分类 TopN（可加 category）；对比两个月时请对每个月各调用一次

【编排规则】
- 涉及收支/账单/分析/对比/画图/统计：必须先调用工具，禁止空谈。
- 简单「本月收支」：优先 1 次 aggregate_stats（或 query_bills）。
- 「对比近两个月 / 对比餐饮」等：第 1 步查第一个区间，第 2 步查第二个区间（最多 2 轮工具）。
- 模糊时间以今天 {today_str} 推算：本月=本月1号至今；最近两个月=上月1号至今；今年=本年1月1日至今。
- 不要向用户确认日期，直接推算后调用工具。
"""


def _filter_bills_query(db, models, user_id: int, start: str, end: str, query_type: str, category: Optional[str]):
    q = db.query(models.Bill).filter(
        models.Bill.user_id == user_id,
        models.Bill.date >= start,
        models.Bill.date <= end,
        models.Bill.is_deleted == 0,
    )
    if query_type == "expense":
        q = q.filter(models.Bill.type == "expense")
    elif query_type == "income":
        q = q.filter(models.Bill.type == "income")
    if category and str(category).strip():
        q = q.filter(models.Bill.category == str(category).strip())
    return q


def execute_query_bills(db, models, user_id: int, args: dict[str, Any]) -> ToolQueryResult:
    start, end, date_err, notes = normalize_date_range(args.get("start_date"), args.get("end_date"))
    if date_err:
        r = failure_tool_result(date_err)
        r.notes.extend(notes)
        return r
    query_type = args.get("query_type") or "all"
    if query_type not in ("expense", "income", "all"):
        query_type = "all"
    category = args.get("category")
    try:
        bills = _filter_bills_query(db, models, user_id, start, end, query_type, category).all()
        result = build_tool_result_from_bills(bills, start, end, query_type)
        result.notes.extend(notes)
        if category:
            result.db_result_str = (
                f"【工具 query_bills | 分类={category}】\n" + result.db_result_str
            )
        else:
            result.db_result_str = "【工具 query_bills】\n" + result.db_result_str
        result.notes.append("tool:query_bills")
        return result
    except Exception as e:
        logger.exception("query_bills failed")
        return failure_tool_result(f"query_bills 查询失败：数据库暂时不可用（{type(e).__name__}）")


def execute_aggregate_stats(db, models, user_id: int, args: dict[str, Any]) -> ToolQueryResult:
    start, end, date_err, notes = normalize_date_range(args.get("start_date"), args.get("end_date"))
    if date_err:
        r = failure_tool_result(date_err)
        r.notes.extend(notes)
        return r
    query_type = args.get("query_type") or "all"
    if query_type not in ("expense", "income", "all"):
        query_type = "all"
    category = args.get("category")
    try:
        top_n = int(args.get("top_n") or 5)
    except (TypeError, ValueError):
        top_n = 5
    top_n = max(1, min(top_n, 20))

    try:
        bills = _filter_bills_query(db, models, user_id, start, end, query_type, category).all()
        total_income = _round_money(sum(float(b.amount) for b in bills if b.type == "income"))
        total_expense = _round_money(sum(float(b.amount) for b in bills if b.type == "expense"))
        balance = _round_money(total_income - total_expense)

        cat_sums: dict[str, float] = defaultdict(float)
        for b in bills:
            if query_type == "all" and b.type == "income":
                # TopN 默认看支出分类更有「消费分析」意义；纯收入查询则看收入分类
                continue
            if query_type == "income" and b.type != "income":
                continue
            if query_type == "expense" and b.type != "expense":
                continue
            if query_type == "all" and b.type != "expense":
                continue
            cat_sums[b.category or "未分类"] += float(b.amount)

        # 若 all 且没有支出，回退到全部类型分类
        if not cat_sums and bills:
            for b in bills:
                cat_sums[b.category or "未分类"] += float(b.amount)

        ranked = sorted(cat_sums.items(), key=lambda x: x[1], reverse=True)[:top_n]
        daily: dict[str, dict[str, float]] = {}
        if query_type == "income":
            empty = total_income == 0
        elif query_type == "expense":
            empty = total_expense == 0
        else:
            empty = len(bills) == 0 or (total_income == 0 and total_expense == 0)

        allowed = build_allowed_values(total_income, total_expense, balance, daily)
        for _, amt in ranked:
            allowed.add(_round_money(amt))

        header = f"【工具 aggregate_stats】时间区间：{start} 至 {end}"
        if category:
            header += f" | 分类过滤={category}"
        lines = [
            header,
            f"总收入：{total_income}元",
            f"总支出：{total_expense}元",
            f"净结余：{balance}元",
            f"账单条数：{len(bills)}",
            f"分类 Top{top_n}：",
        ]
        if ranked:
            for i, (name, amt) in enumerate(ranked, 1):
                lines.append(f"  {i}. {name}: {_round_money(amt)}元")
        else:
            lines.append("  （无分类汇总）")

        if empty:
            base = format_db_result_str(
                start, end, query_type, total_income, total_expense, balance, daily, True
            )
            db_str = header + "\n" + base
        else:
            db_str = "\n".join(lines)

        return ToolQueryResult(
            ok=True,
            empty=empty,
            start_date=start,
            end_date=end,
            query_type=query_type,
            total_income=total_income,
            total_expense=total_expense,
            balance=balance,
            daily=daily,
            db_result_str=db_str,
            allowed_values=allowed,
            notes=notes + ["tool:aggregate_stats"],
        )
    except Exception as e:
        logger.exception("aggregate_stats failed")
        return failure_tool_result(f"aggregate_stats 查询失败：数据库暂时不可用（{type(e).__name__}）")


def execute_finance_tool(name: str, args_raw: str, db, models, user_id: int) -> ToolQueryResult:
    args, parse_err = parse_tool_arguments(args_raw)
    if parse_err or not args:
        # 轻量纠错：再试一次截取（parse_tool_arguments 已含）；仍失败则失败语义
        return failure_tool_result(parse_err or f"工具 {name} 参数无效")

    if name == "query_bills":
        return execute_query_bills(db, models, user_id, args)
    if name == "aggregate_stats":
        return execute_aggregate_stats(db, models, user_id, args)
    return failure_tool_result(f"未知工具：{name}")


def merge_tool_results(results: list[ToolQueryResult]) -> ToolQueryResult:
    if not results:
        return failure_tool_result("未执行任何工具，无法生成财务结论。")
    if len(results) == 1:
        return results[0]

    ok = any(r.ok for r in results)
    # 多段对比：任一段有数据则允许画图（用并集对账）
    empty = all((not r.ok) or r.empty for r in results)
    allowed: set[float] = {0.0}
    for r in results:
        allowed |= set(r.allowed_values or {0.0})
    blocks = [r.db_result_str for r in results]
    total_income = _round_money(sum(r.total_income for r in results if r.ok))
    total_expense = _round_money(sum(r.total_expense for r in results if r.ok))
    balance = _round_money(total_income - total_expense)
    notes: list[str] = []
    for r in results:
        notes.extend(r.notes)

    return ToolQueryResult(
        ok=ok,
        empty=empty,
        start_date=results[0].start_date,
        end_date=results[-1].end_date,
        query_type="all",
        total_income=total_income,
        total_expense=total_expense,
        balance=balance,
        daily={},
        db_result_str="\n\n-----\n\n".join(blocks),
        error_message=None if ok else "部分或全部工具失败",
        allowed_values=allowed,
        notes=notes + ["merged_multi_tool"],
    )


def message_to_dict(message: Any) -> dict[str, Any]:
    """把 OpenAI SDK message 转成可再送入 API 的 dict。"""
    tool_calls = getattr(message, "tool_calls", None)
    data: dict[str, Any] = {
        "role": getattr(message, "role", "assistant"),
        "content": getattr(message, "content", None) or "",
    }
    if tool_calls:
        data["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in tool_calls
        ]
    return data


def run_finance_tool_loop(
    client: Any,
    *,
    db: Any,
    models: Any,
    user_id: int,
    planner_messages: list[dict[str, Any]],
    max_rounds: int = MAX_TOOL_ROUNDS,
    model: str = FINANCE_CHAT_MODEL,
    replan_on_failure: bool = True,
    max_replans: int = MAX_FAILURE_REPLANS,
) -> tuple[Optional[ToolQueryResult], list[dict[str, Any]], bool]:
    """
    有限步工具循环（带一次失败重规划）。

    返回 (merged_tool_result | None, tool_trace, used_tools)。
    used_tools=False 表示模型未调工具（走闲聊）。

    重规划不额外消耗预算：整轮工具失败时，把「请修正参数重试」语义
    回灌给模型，复用下一轮（仍在 max_rounds 内）让它自己改参数。
    重试成功 → 丢弃失败块，最终只合并成功结果；
    重试仍失败 / 模型放弃 → 恢复失败语义交 Stage2 拒答，不吞错。
    """
    working = list(planner_messages)
    trace: list[dict[str, Any]] = []
    collected: list[ToolQueryResult] = []
    failed_buffer: list[ToolQueryResult] = []
    replans_used = 0
    retried_tools: set[str] = set()

    for round_idx in range(1, max_rounds + 1):
        response = client.chat.completions.create(
            model=model,
            messages=working,
            tools=FINANCE_TOOLS,
            tool_choice="auto",
            temperature=0.2,
        )
        msg = response.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []

        if not tool_calls:
            if not collected and not failed_buffer:
                return None, trace, False
            # 已有工具结果且模型不再调工具 → 结束编排，交给 NLG
            break

        working.append(message_to_dict(msg))

        round_results: list[tuple[Any, str, str, ToolQueryResult]] = []
        for tc in tool_calls:
            name = tc.function.name
            args_raw = tc.function.arguments
            result = execute_finance_tool(name, args_raw, db, models, user_id)
            round_results.append((tc, name, args_raw, result))

        all_failed = all(not r.ok for _, _, _, r in round_results)
        can_replan = (
            replan_on_failure
            and all_failed
            and replans_used < max_replans
            and round_idx < max_rounds
        )

        if can_replan:
            replans_used += 1
            for tc, name, args_raw, result in round_results:
                failed_buffer.append(result)
                retried_tools.add(name)
                step = {
                    "round": round_idx,
                    "tool": name,
                    "arguments": args_raw,
                    "ok": False,
                    "empty": result.empty,
                    "summary": (result.db_result_str or "")[:240],
                    "error": result.error_message,
                    "attempt": 1,
                    "replan": True,
                }
                trace.append(step)
                logger.info(
                    "finance_tool_replan round=%s tool=%s reason=%s",
                    round_idx,
                    name,
                    result.error_message,
                )
                print(f"🧭 tool_replan: {json.dumps(step, ensure_ascii=False)}")
                # 失败语义改写为重规划指令：让模型改参数再试，而不是直接放弃
                working.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": REPLAN_TOOL_MESSAGE.format(
                            reason=result.error_message or "参数或查询无效"
                        ),
                    }
                )
            # 复用下一轮，不额外增加 LLM 调用
            continue

        recovered = bool(retried_tools) and any(r.ok for _, _, _, r in round_results)
        for tc, name, args_raw, result in round_results:
            collected.append(result)
            step = {
                "round": round_idx,
                "tool": name,
                "arguments": args_raw,
                "ok": result.ok,
                "empty": result.empty,
                "summary": (result.db_result_str or "")[:240],
                "error": result.error_message,
                "attempt": replans_used + 1,
                "replan": False,
                "recovered": recovered,
            }
            trace.append(step)
            logger.info(
                "finance_tool_trace round=%s tool=%s ok=%s empty=%s replan_recovery=%s",
                round_idx,
                name,
                result.ok,
                result.empty,
                recovered,
            )
            print(f"🧭 tool_trace: {json.dumps(step, ensure_ascii=False)}")

            working.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result.db_result_str or result.error_message or "",
                }
            )

        # 达到轮次上限：不再让模型继续要工具
        if round_idx >= max_rounds:
            break

    # 触发过重规划但未成功：恢复降级语义，只保留最后一次失败块（避免重复错误文本）
    if failed_buffer and not any(r.ok for r in collected):
        collected = collected[-1:] if collected else failed_buffer[-1:]

    if not collected:
        return None, trace, False
    return merge_tool_results(collected), trace, True
