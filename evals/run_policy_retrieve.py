"""
理赔 RAG 检索冒烟：对 evals/cases_policy.jsonl 跑 similarity_search，打印 sources。
不调用生成模型，便于验证「请求链路必然检索」与同义改写召回。

用法（项目根目录）:
  python evals/run_policy_retrieve.py
"""
from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from langchain_community.embeddings import ZhipuAIEmbeddings
from langchain_community.vectorstores import Chroma

from policy_rag import DEFAULT_TOP_K, retrieve_policy_docs, sources_for_client

CASES_PATH = os.path.join(os.path.dirname(__file__), "cases_policy.jsonl")
DB_DIR = os.path.join(ROOT, "chroma_db_insurance")


def load_cases() -> list[dict]:
    cases = []
    with open(CASES_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def main() -> int:
    if not os.path.isdir(DB_DIR):
        print(f"❌ 未找到向量库目录: {DB_DIR}")
        print("   请先运行: python scripts/build_knowledge_db.py")
        return 1

    print("加载 insurance_vectorstore ...")
    embeddings = ZhipuAIEmbeddings(model="embedding-2")
    vectorstore = Chroma(persist_directory=DB_DIR, embedding_function=embeddings)

    cases = load_cases()
    print(f"共 {len(cases)} 条用例，top_k={DEFAULT_TOP_K}\n")

    empty = 0
    for case in cases:
        q = case["question"]
        sources = retrieve_policy_docs(vectorstore, q, k=DEFAULT_TOP_K)
        client_srcs = sources_for_client(sources)
        print(f"[{case['id']}] type={case['type']}")
        print(f"  Q: {q}")
        if not client_srcs:
            empty += 1
            print("  sources: (empty)")
        else:
            for s in client_srcs:
                page = f"p.{s['page']}" if s.get("page") else "p.?"
                print(f"  - [{s['index']}] {page} score={s.get('score')}: {s['snippet'][:80]}")
        print(f"  expect: {case.get('expect')}\n")

    print(f"完成。召回为空条数: {empty}/{len(cases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
