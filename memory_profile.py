"""
理财习惯侧写（阶段 E4）：
- 固定侧写检索（消费习惯 财务痛点）
- 按用户问题 similarity_search(user_query)
两者并存、去重后注入 Prompt。
"""
from __future__ import annotations

from typing import Any, Optional


FIXED_MEMORY_QUERY = "消费习惯 财务痛点"


def load_finance_side_profile(
    vectorstore: Any,
    user_id: int,
    user_query: str,
    *,
    fixed_k: int = 2,
    query_k: int = 3,
) -> tuple[str, dict[str, Any]]:
    """
    返回 (注入用文本, memory_trace)。
    vectorstore 不可用时返回「暂无」。
    """
    trace: dict[str, Any] = {
        "fixed_query": FIXED_MEMORY_QUERY,
        "user_query": user_query,
        "fixed_hits": [],
        "query_hits": [],
    }

    if vectorstore is None:
        return "暂无", {**trace, "error": "financial_vectorstore_unavailable"}

    fixed_docs: list[Any] = []
    query_docs: list[Any] = []

    try:
        fixed_docs = vectorstore.similarity_search(
            FIXED_MEMORY_QUERY,
            k=fixed_k,
            filter={"user_id": user_id},
        )
    except Exception as e:
        print(f"固定侧写检索失败: {e}")
        trace["fixed_error"] = str(e)

    try:
        q = (user_query or "").strip() or FIXED_MEMORY_QUERY
        query_docs = vectorstore.similarity_search(
            q,
            k=query_k,
            filter={"user_id": user_id},
        )
    except Exception as e:
        print(f"问题条件习惯检索失败: {e}")
        trace["query_error"] = str(e)

    def _snip(doc: Any, limit: int = 80) -> str:
        text = (getattr(doc, "page_content", None) or "").strip()
        return text if len(text) <= limit else text[:limit].rstrip() + "…"

    trace["fixed_hits"] = [_snip(d) for d in fixed_docs]
    trace["query_hits"] = [_snip(d) for d in query_docs]

    # 去重：问题检索优先保留顺序，再补固定侧写
    seen: set[str] = set()
    query_lines: list[str] = []
    fixed_lines: list[str] = []

    for d in query_docs:
        t = (getattr(d, "page_content", None) or "").strip()
        if t and t not in seen:
            seen.add(t)
            query_lines.append(f"- {t}")

    for d in fixed_docs:
        t = (getattr(d, "page_content", None) or "").strip()
        if t and t not in seen:
            seen.add(t)
            fixed_lines.append(f"- {t}")

    parts: list[str] = []
    if query_lines:
        parts.append("【与当前问题相关的习惯侧写】\n" + "\n".join(query_lines))
    if fixed_lines:
        parts.append("【稳定财务痛点侧写】\n" + "\n".join(fixed_lines))

    if not parts:
        return "暂无", trace

    print(
        f"[memory_trace] query_hits={len(trace['query_hits'])} "
        f"fixed_hits={len(trace['fixed_hits'])}"
    )
    return "\n\n".join(parts), trace
