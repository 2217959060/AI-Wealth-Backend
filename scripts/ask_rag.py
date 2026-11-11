"""
本地调试：保险条款 RAG（与线上 /ai/ask_policy 共用 policy_rag）。

用法（在项目根目录）:
  python scripts/ask_rag.py
  python scripts/ask_rag.py "等待期出险能否理赔？"
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# 保证可从仓库根目录导入 policy_rag
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from datetime import date

from langchain_community.embeddings import ZhipuAIEmbeddings
from langchain_community.vectorstores import Chroma
from openai import OpenAI

from llm_config import CHAT_MODEL, EMBEDDING_MODEL
from policy_rag import (
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_K,
    HARD_REFUSE_REPLY,
    assess_policy_grounding,
    build_policy_messages,
    filter_sources_by_distance,
    format_context_from_sources,
    retrieve_policy_docs,
    sources_for_client,
)

client = OpenAI(
    api_key=os.environ["ZHIPUAI_API_KEY"],
    base_url="https://open.bigmodel.cn/api/paas/v4/",
)

DB_DIR = os.path.join(ROOT, "chroma_db_insurance")


def ask_insurance_advisor(question: str, k: int = DEFAULT_TOP_K) -> str:
    print(f"\n🙋‍♂️ 用户提问：{question}")
    print("🔍 正在检索本地保险条款向量库...")

    embeddings = ZhipuAIEmbeddings(model=EMBEDDING_MODEL)
    vectorstore = Chroma(persist_directory=DB_DIR, embedding_function=embeddings)

    raw = retrieve_policy_docs(vectorstore, question, k=k, max_distance=None)
    sources = filter_sources_by_distance(raw)
    decision = assess_policy_grounding(sources, had_raw_hits=bool(raw))

    print("\n=== 🎯 召回片段 (sources) ===")
    for s in sources_for_client(decision.sources):
        page = f"p.{s['page']}" if s.get("page") else "p.?"
        score = s.get("score")
        score_hint = f" score={score}" if score is not None else ""
        print(f"[{s['index']}] {page}{score_hint}: {s['snippet']}")

    if not decision.allow_generate:
        print(f"🛡️ 代码硬拒答: {decision.guards} ({decision.reason})")
        print("\n=== 💡 理赔顾问回复 ===")
        print(HARD_REFUSE_REPLY)
        print("================================\n")
        return HARD_REFUSE_REPLY

    today_str = date.today().strftime("%Y-%m-%d")
    messages = build_policy_messages(
        today_str=today_str,
        question=question,
        context_str=format_context_from_sources(decision.sources),
    )

    print("\n🧠 AI 正在基于条款生成回复...")
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,
        temperature=DEFAULT_TEMPERATURE,
    )
    answer = response.choices[0].message.content or ""
    print("\n=== 💡 理赔顾问回复 ===")
    print(answer)
    print("================================\n")
    return answer


if __name__ == "__main__":
    default_q = (
        "如果我因为酒后驾驶机动车发生了严重车祸，导致双腿截肢（属于重大疾病），"
        "保险公司会赔钱吗？"
    )
    q = sys.argv[1] if len(sys.argv) > 1 else default_q
    ask_insurance_advisor(q)
