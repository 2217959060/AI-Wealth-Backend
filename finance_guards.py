"""
理财管家工程闸门（阶段 C）：
- 工具参数 / 日期校验（失败语义）
- 空结果禁止出图（程序级剥除 ```echarts）
- ECharts 数值与当次 tool 结果对账

供 main.py 与 evals/run_finance_checks.py 共用。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("finance_guards")

ECHARTS_BLOCK_RE = re.compile(r"```echarts\s*([\s\S]*?)```", re.IGNORECASE)


@dataclass
class ToolQueryResult:
    """一次 get_financial_data 的结构化结果，供 Prompt 与闸门共用。"""

    ok: bool
    empty: bool
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    query_type: str = "all"
    total_income: float = 0.0
    total_expense: float = 0.0
    balance: float = 0.0
    daily: dict[str, dict[str, float]] = field(default_factory=dict)
    db_result_str: str = ""
    error_message: Optional[str] = None
    # 图表允许出现的数值（含 0 与日汇总、总汇总）
    allowed_values: set[float] = field(default_factory=lambda: {0.0})
    notes: list[str] = field(default_factory=list)


def parse_tool_arguments(raw: Optional[str]) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """解析 tool 参数 JSON；失败返回 (None, 原因)。"""
    if raw is None or not str(raw).strip():
        return None, "工具参数为空"
    text = str(raw).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data, None
        return None, "工具参数不是 JSON 对象"
    except json.JSONDecodeError:
        # 容错：截取第一个 {...}
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                if isinstance(data, dict):
                    return data, None
            except json.JSONDecodeError:
                pass
        return None, "工具参数 JSON 解析失败"


def normalize_date_range(
    start_date: Any, end_date: Any
) -> tuple[Optional[str], Optional[str], Optional[str], list[str]]:
    """
    校验并规范化日期。
    返回 (start, end, error_message, notes)。
    区间倒置时自动对调并记 note，不进入瞎画图。
    """
    notes: list[str] = []
    if start_date is None or end_date is None or str(start_date).strip() == "" or str(end_date).strip() == "":
        return None, None, "缺少 start_date 或 end_date，请重新说明查询时间范围。", notes
    try:
        s = datetime.strptime(str(start_date).strip()[:10], "%Y-%m-%d").date()
        e = datetime.strptime(str(end_date).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return (
            None,
            None,
            f"日期格式非法（收到 start={start_date!r}, end={end_date!r}），请使用 YYYY-MM-DD。",
            notes,
        )
    if s > e:
        s, e = e, s
        notes.append("date_range_swapped")
    return s.isoformat(), e.isoformat(), None, notes


def _round_money(v: float) -> float:
    return round(float(v), 2)


def build_allowed_values(
    total_income: float,
    total_expense: float,
    balance: float,
    daily: dict[str, dict[str, float]],
) -> set[float]:
    allowed = {0.0, _round_money(total_income), _round_money(total_expense), _round_money(balance)}
    for day in daily.values():
        allowed.add(_round_money(day.get("income", 0)))
        allowed.add(_round_money(day.get("expense", 0)))
    return allowed


def format_db_result_str(
    start_date: str,
    end_date: str,
    query_type: str,
    total_income: float,
    total_expense: float,
    balance: float,
    daily: dict[str, dict[str, float]],
    empty: bool,
) -> str:
    if empty:
        if query_type == "income":
            return (
                f"时间区间：{start_date} 至 {end_date}\n"
                "🚨 查询结果：这段时间内【没有任何收入记录】！请用纯文本告知用户，严禁画图！"
            )
        if query_type == "expense":
            return (
                f"时间区间：{start_date} 至 {end_date}\n"
                "🚨 查询结果：这段时间内【没有任何支出记录】！请用纯文本告知用户，严禁画图！"
            )
        return (
            f"时间区间：{start_date} 至 {end_date}\n"
            "🚨 查询结果：这段时间内【没有任何账单记录】（收入与支出均为 0）！"
            "请用纯文本告知用户，严禁画图、严禁编造金额！"
        )

    lines = [
        f"时间区间：{start_date} 至 {end_date}",
        f"总收入：{total_income}元",
        f"总支出：{total_expense}元",
        f"净结余：{balance}元",
        "",
        "【每日收支精确汇总】(画图时请严格直接使用以下数据，绝不可漏掉日期或自行计算)：",
    ]
    for d in sorted(daily.keys()):
        lines.append(
            f"- {d}: 收入 {daily[d]['income']}元, 支出 {daily[d]['expense']}元"
        )
    return "\n".join(lines)


def build_tool_result_from_bills(
    bills: list[Any],
    start_date: str,
    end_date: str,
    query_type: str = "all",
) -> ToolQueryResult:
    """从 ORM / 简易对象列表汇总（对象需有 type/amount/date）。"""
    from collections import defaultdict

    daily: dict[str, dict[str, float]] = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
    total_income = 0.0
    total_expense = 0.0

    for b in bills:
        b_type = getattr(b, "type", None)
        amount = float(getattr(b, "amount", 0) or 0)
        raw_date = getattr(b, "date", "")
        date_str = raw_date.strftime("%Y-%m-%d") if hasattr(raw_date, "strftime") else str(raw_date)[:10]
        if b_type == "income":
            total_income += amount
            daily[date_str]["income"] += amount
        elif b_type == "expense":
            total_expense += amount
            daily[date_str]["expense"] += amount

    total_income = _round_money(total_income)
    total_expense = _round_money(total_expense)
    balance = _round_money(total_income - total_expense)
    daily_plain = {
        k: {"income": _round_money(v["income"]), "expense": _round_money(v["expense"])}
        for k, v in daily.items()
    }

    if query_type == "income":
        empty = total_income == 0
    elif query_type == "expense":
        empty = total_expense == 0
    else:
        empty = len(bills) == 0 or (total_income == 0 and total_expense == 0)

    allowed = build_allowed_values(total_income, total_expense, balance, daily_plain)
    db_str = format_db_result_str(
        start_date, end_date, query_type, total_income, total_expense, balance, daily_plain, empty
    )
    return ToolQueryResult(
        ok=True,
        empty=empty,
        start_date=start_date,
        end_date=end_date,
        query_type=query_type,
        total_income=total_income,
        total_expense=total_expense,
        balance=balance,
        daily=daily_plain,
        db_result_str=db_str,
        allowed_values=allowed,
    )


def failure_tool_result(message: str) -> ToolQueryResult:
    return ToolQueryResult(
        ok=False,
        empty=True,
        db_result_str=(
            f"🚨 查询未能完成：{message}\n"
            "请用纯文本向用户说明原因，严禁编造任何金额，严禁输出 echarts 图表！"
        ),
        error_message=message,
        allowed_values={0.0},
    )


def has_echarts_block(text: str) -> bool:
    return bool(ECHARTS_BLOCK_RE.search(text or ""))


def strip_echarts_blocks(text: str) -> str:
    cleaned = ECHARTS_BLOCK_RE.sub("", text or "")
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _extract_numbers_from_series_data(data: Any) -> list[float]:
    nums: list[float] = []
    if not isinstance(data, list):
        return nums
    for item in data:
        if isinstance(item, (int, float)):
            nums.append(_round_money(float(item)))
        elif isinstance(item, dict) and "value" in item:
            try:
                nums.append(_round_money(float(item["value"])))
            except (TypeError, ValueError):
                continue
    return nums


def parse_echarts_payload(raw_json: str) -> tuple[Optional[dict], Optional[str]]:
    try:
        obj = json.loads(raw_json.strip())
    except json.JSONDecodeError as e:
        return None, f"echarts_json_invalid:{e}"
    if not isinstance(obj, dict):
        return None, "echarts_not_object"
    return obj, None


def validate_echarts_against_tool(
    chart: dict[str, Any], tool: ToolQueryResult, tol: float = 0.02
) -> tuple[bool, str]:
    """
    校验 series[].data 数值均落在当次 tool 允许集合内（允许 0）。
    并对 xAxis 与 series 长度做基本对齐检查。
    """
    series = chart.get("series")
    if not isinstance(series, list) or not series:
        return False, "missing_series"

    x_data = None
    x_axis = chart.get("xAxis")
    if isinstance(x_axis, dict):
        x_data = x_axis.get("data")
    elif isinstance(x_axis, list) and x_axis and isinstance(x_axis[0], dict):
        x_data = x_axis[0].get("data")

    for s in series:
        if not isinstance(s, dict):
            return False, "series_item_invalid"
        data = s.get("data")
        nums = _extract_numbers_from_series_data(data)
        if isinstance(x_data, list) and len(nums) != len(x_data):
            return False, "xaxis_series_length_mismatch"
        for n in nums:
            if not any(abs(n - a) <= tol for a in tool.allowed_values):
                return False, f"value_not_in_tool:{n}"

    return True, "ok"


def apply_output_guards(
    reply: str,
    tool: Optional[ToolQueryResult],
) -> tuple[str, list[str]]:
    """
    程序级闸门：
    - 无 tool / 失败 / 空结果：剥除全部 echarts
    - 有数据：逐块校验；任一块不对账则剥除全部 echarts，保留文字
    """
    events: list[str] = []
    text = reply or ""

    if tool is None:
        return text, events

    if not tool.ok or tool.empty:
        if has_echarts_block(text):
            text = strip_echarts_blocks(text)
            events.append("empty_or_fail_gate_stripped_echarts")
            logger.info("finance_guard: stripped echarts (empty/fail)")
        if not text.strip():
            text = (
                tool.error_message
                or "这段时间内没有查询到可用账单记录，已取消图表输出，避免展示不实数据。"
            )
            events.append("empty_gate_fallback_text")
        return text, events

    # 有数据：校验每一块
    matches = list(ECHARTS_BLOCK_RE.finditer(text))
    if not matches:
        return text, events

    for m in matches:
        chart, err = parse_echarts_payload(m.group(1))
        if err or chart is None:
            text = strip_echarts_blocks(text)
            events.append(f"chart_parse_failed_stripped:{err}")
            logger.info("finance_guard: chart parse failed, stripped")
            break
        ok, reason = validate_echarts_against_tool(chart, tool)
        if not ok:
            text = strip_echarts_blocks(text)
            events.append(f"chart_validation_failed_stripped:{reason}")
            logger.info("finance_guard: chart validation failed (%s), stripped", reason)
            break
    else:
        events.append("chart_validation_passed")

    return text, events


def build_stage2_system_prompt(
    today_str: str,
    tone: str,
    tool: ToolQueryResult,
) -> str:
    chart_rule = (
        "当前查询【无记录或失败】：你必须只用纯文本说明，【严禁】输出任何 ```echarts 代码块，【严禁】编造金额。"
        if (not tool.ok or tool.empty)
        else """当前查询【有真实数据】：若做收支分析/对比/画图，可在文末输出 ```echarts 代码块；数字必须来自下方检索结果，缺失日期用 0 占位。"""
    )
    return f"""你是用户的私人财务管家。今天是 {today_str}。请严格基于提供的最新数据库结果回答。

【🎭 角色扮演绝对红线（Show, Don't Tell）】
你现在的性格设定是：【{tone}】。
严禁在回复中暴露你的设定！直接进入角色。

【🚨 防幻觉与上下文污染致命红线】
1. 【绝对无视历史】：必须且只能使用下方「当前数据库检索结果」。禁止照抄对话历史中的旧金额、旧日期！
2. {chart_rule}

【📊 图表规范】（仅在有数据且需要画图时）
```echarts
{{
  "title": {{"text": "图表标题"}},
  "tooltip": {{"trigger": "axis"}},
  "legend": {{"left": "left", "top": "top"}},
  "xAxis": {{"type": "category", "data": ["日期1", "日期2"]}},
  "yAxis": {{"type": "value"}},
  "series": [
    {{"name": "收入", "type": "bar", "data": [0, 0], "itemStyle": {{"color": "#10b981"}}}},
    {{"name": "支出", "type": "bar", "data": [0, 0], "itemStyle": {{"color": "#ef4444"}}}}
  ]
}}
```
1. 必须被 ```echarts 与 ``` 包裹。
2. xAxis.data 长度必须与每个 series.data 长度相等。
3. series 中所有数值必须来自检索结果（可用 0 占位）。
"""
