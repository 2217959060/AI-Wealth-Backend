import os
import re
from dotenv import load_dotenv   # 👈 新增这一行
load_dotenv()                    # 👈 新增这一行

from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import ZhipuAIEmbeddings
from openai import OpenAI

# ================= 1. 填入你的钥匙 =================

client = OpenAI(
    api_key=os.environ["ZHIPUAI_API_KEY"],
    base_url="https://open.bigmodel.cn/api/paas/v4/"
)


def ask_insurance_advisor(question: str):
    print(f"\n🙋‍♂️ 用户提问：{question}")

    # ================= 2. 唤醒本地知识大脑 (Retrieval) =================
    print("🔍 正在去 Chroma 向量数据库中翻阅保险条款...")
    embeddings = ZhipuAIEmbeddings(model="embedding-2")
    # 连接我们刚才建好的本地数据库
    vectorstore = Chroma(persist_directory="./chroma_db_insurance", embedding_function=embeddings)

    # 核心魔法：语义检索！找出与问题最相关的 3 个文本块
    docs = vectorstore.similarity_search(question, k=3)

    context_str = ""
    print("\n=== 🎯 向量库秒级召回的原文条款 ===")
    for i, doc in enumerate(docs):
        # 打印出找出来的原文前几句话，让你亲眼看看它找得准不准
        print(f"片段 {i + 1}: {doc.page_content[:60]}...")
        context_str += f"【参考条款 {i + 1}】\n{doc.page_content}\n\n"

    # ================= 3. 大模型结合知识进行解答 (Generation) =================
    print("\n🧠 AI 正在研读条款并生成专业回复...")

    # 构建极其严谨的 Prompt
    prompt = f"""
    你是一个专业的、铁面无私的保险理赔专家。
    请你【严格依据】下面提供的参考条款，来解答用户的问题。
    ⚠️ 警告：
    1. 如果条款中包含了该问题，请明确给出结论，并引用条款原话。
    2. 如果提供的条款中【完全没有提及】相关内容，请必须如实回答“根据当前条款无法确定”，绝不允许凭空捏造和瞎编！

    {context_str}

    用户问题：{question}
    """

    response = client.chat.completions.create(
        model="glm-4-flash",
        messages=[
            {"role": "system", "content": "你是一个严格依据事实回答问题的理赔AI助手。"},
            {"role": "user", "content": prompt}
        ],
        # 🌟 架构师细节：把温度调到 0.1。面对严谨的法律合同，我们需要 AI 放弃发散性创造，像机器一样精准！
        temperature=0.1
    )

    print("\n=== 💡 专属 AI 理赔顾问回复 ===")
    print(response.choices[0].message.content)
    print("================================\n")


if __name__ == "__main__":
    # 我们可以测一个极其经典的重疾险陷阱问题
    test_question = "如果我因为酒后驾驶机动车发生了严重车祸，导致双腿截肢（属于重大疾病），保险公司会赔钱吗？"

    ask_insurance_advisor(test_question)