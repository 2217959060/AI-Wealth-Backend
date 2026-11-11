"""
保险理赔 RAG：检索 → 组装上下文 / sources → 构造 grounded Prompt。

供 main.py 的 /ai/ask_policy 与 scripts/ask_rag.py 共用，避免脚本与线上分叉。

拒答分层：
- Prompt 软约束：有召回但仍可能不相关时，要求模型说 REFUSE_PHRASE
- 代码硬闸门：空召回（或距离门槛滤光）时跳过 LLM，直接拒答
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

# 检索与生成默认参数（面试可讲的固定超参）
DEFAULT_TOP_K = 4
DEFAULT_TEMPERATURE = 0.1
SNIPPET_LEN = 120

# Chroma 默认 L2：越小越相关。
# 默认不过滤；可用环境变量 POLICY_RAG_MAX_DISTANCE 开启硬门槛（如 1.35）。
def _env_max_distance() -> Optional[float]:
    raw = os.getenv("POLICY_RAG_MAX_DISTANCE", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


MAX_DISTANCE: Optional[float] = _env_max_distance()

REFUSE_PHRASE = "根据当前条款无法确定"
HARD_REFUSE_REPLY = (
    f"{REFUSE_PHRASE}。当前未检索到与问题足够相关的保险条款片段，"
    "无法基于条款作答，请换用保单相关问题，或核对是否已加载对应条款库。"
)


@dataclass
class PolicyGroundingDecision:
    """检索后是否允许进入 LLM 生成。"""

    allow_generate: bool
    reason: str  # ok | empty_retrieval | distance_filtered
    sources: list[dict[str, Any]]
    guards: list[str]


def _page_from_metadata(metadata: dict[str, Any] | None) -> Optional[int]:
    if not metadata:
        return None
    page = metadata.get("page")
    if page is None:
        page = metadata.get("page_number")
    if page is None:
        return None
    try:
        # PyPDFLoader 多为 0-based
        return int(page) + 1
    except (TypeError, ValueError):
        return None


def _snippet(text: str, length: int = SNIPPET_LEN) -> str:
    text = (text or "").strip()
    if len(text) <= length:
        return text
    return text[:length].rstrip() + "…"


def retrieve_policy_docs(
    vectorstore: Any,
    question: str,
    k: int = DEFAULT_TOP_K,
    max_distance: Optional[float] = MAX_DISTANCE,
) -> list[dict[str, Any]]:
    """
    对问题做向量检索，返回可序列化的 sources 列表。
    每项含：index, snippet, page, score, content。
    """
    if vectorstore is None:
        return []

    scored: list[tuple[Any, Optional[float]]] = []
    try:
        pairs = vectorstore.similarity_search_with_score(question, k=k)
        scored = [(doc, float(score)) for doc, score in pairs]
    except Exception:
        docs = vectorstore.similarity_search(question, k=k)
        scored = [(doc, None) for doc in docs]

    sources: list[dict[str, Any]] = []
    for i, (doc, score) in enumerate(scored, start=1):
        if max_distance is not None and score is not None and score > max_distance:
            continue
        content = (getattr(doc, "page_content", None) or "").strip()
        if not content:
            continue
        meta = getattr(doc, "metadata", None) or {}
        sources.append(
            {
                "index": i,
                "snippet": _snippet(content),
                "page": _page_from_metadata(meta),
                "score": round(score, 4) if score is not None else None,
                "content": content,
            }
        )
    # 重新编号（过滤后 index 连续，便于 Prompt 引用）
    for i, src in enumerate(sources, start=1):
        src["index"] = i
    return sources


def filter_sources_by_distance(
    sources: list[dict[str, Any]],
    max_distance: Optional[float] = MAX_DISTANCE,
) -> list[dict[str, Any]]:
    """对已检索结果按 L2 距离做硬过滤；max_distance=None 时原样返回。"""
    if max_distance is None:
        return list(sources)
    kept: list[dict[str, Any]] = []
    for src in sources:
        score = src.get("score")
        if score is not None and float(score) > max_distance:
            continue
        kept.append(dict(src))
    for i, src in enumerate(kept, start=1):
        src["index"] = i
    return kept


def assess_policy_grounding(
    sources: list[dict[str, Any]],
    *,
    had_raw_hits: bool = False,
) -> PolicyGroundingDecision:
    """
    代码层 grounding 闸门。
    - sources 为空 → 硬拒答（跳过 LLM）
    - had_raw_hits=True 且过滤后为空 → 记为 distance_filtered
    """
    if sources:
        return PolicyGroundingDecision(
            allow_generate=True,
            reason="ok",
            sources=sources,
            guards=[],
        )

    if had_raw_hits:
        reason = "distance_filtered"
        guards = ["policy_hard_refuse_filtered"]
    else:
        reason = "empty_retrieval"
        guards = ["policy_hard_refuse_empty"]

    return PolicyGroundingDecision(
        allow_generate=False,
        reason=reason,
        sources=[],
        guards=guards,
    )


def format_context_from_sources(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "（未检索到与问题相关的保险条款片段）"
    parts: list[str] = []
    for src in sources:
        page_hint = f"（约第 {src['page']} 页）" if src.get("page") else ""
        parts.append(f"【参考条款 {src['index']}】{page_hint}\n{src['content']}")
    return "\n\n".join(parts)


def sources_for_client(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """SSE / API 对外暴露：不含全文，仅摘要与页码。"""
    return [
        {
            "index": s["index"],
            "snippet": s["snippet"],
            "page": s.get("page"),
            "score": s.get("score"),
        }
        for s in sources
    ]


def build_policy_system_prompt(today_str: str, context_str: str) -> str:
    return f"""你是专业的保险理赔顾问。今天是 {today_str}。

请【严格依据】下面提供的参考条款解答用户问题。

⚠️ 硬性规则：
1. 条款中有明确依据时：给出结论，并引用条款原话（可标注【参考条款 N】）。
2. 若参考条款【完全没有提及】或不足以回答：必须如实回答「{REFUSE_PHRASE}」，禁止凭空捏造、补充外部常识当条款。
3. 不要编造条款编号、保额、等待期等未出现在参考条款中的数字或条文。
4. 使用 Markdown（加粗、列表）让排版清晰。

【检索到的保险条款】
{context_str}
"""


def build_policy_messages(
    today_str: str,
    question: str,
    context_str: str,
    history_messages: list[dict[str, str]] | None = None,
    window: int = 6,
) -> list[dict[str, str]]:
    """拼装送入 LLM 的 messages（system 含条款 + 滑动窗口历史）。"""
    system = build_policy_system_prompt(today_str, context_str)
    history = list(history_messages or [])
    if not history or history[-1].get("content") != question:
        history = history + [{"role": "user", "content": question}]
    return [{"role": "system", "content": system}] + history[-window:]
