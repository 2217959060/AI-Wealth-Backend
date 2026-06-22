import os
import re
from dotenv import load_dotenv   # 👈 新增这一行
load_dotenv()                    # 👈 新增这一行
import time
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import ZhipuAIEmbeddings




def build_investment_knowledge_base():
    print("🚀 开始构建公共理财投顾知识库...")
    source_dir = "../data/investment_docs"
    persist_dir = "../chroma_db_investment"

    if not os.path.exists(source_dir):
        print(f"❌ 错误：找不到源文件夹 {source_dir}")
        return

    print("📥 正在读取 PDF 文件...")
    loader = PyPDFDirectoryLoader(source_dir)
    documents = loader.load()
    print(f"✅ 成功读取，共解析出 {len(documents)} 页 PDF 文本。")

    print("✂️ 正在进行智能文本切片...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=600,
        chunk_overlap=60
    )
    chunks = text_splitter.split_documents(documents)

    # ================= 🌟 终极清洗 =================
    print("🧹 正在进行深度清洗与长度压制...")
    valid_chunks = []
    for chunk in chunks:
        # 去除底层空字节和特殊替换符
        cleaned_text = chunk.page_content.replace('\x00', '').replace('\ufffd', '').strip()

        # 强制压制长度！超过 800 字的直接腰斩，防止撑爆 API 参数
        if len(cleaned_text) > 800:
            cleaned_text = cleaned_text[:800]

        if len(cleaned_text) > 10:
            chunk.page_content = cleaned_text
            valid_chunks.append(chunk)

    print(f"✅ 清洗完毕，剩余 {len(valid_chunks)} 个纯净区块准备入库。")

    print("🤖 正在呼叫智谱 Embedding 接口...")
    embeddings = ZhipuAIEmbeddings(model="embedding-2")

    vectorstore = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings
    )

    # 缩小批次，降低“连坐”风险
    batch_size = 20
    total_chunks = len(valid_chunks)

    for i in range(0, total_chunks, batch_size):
        batch = valid_chunks[i: i + batch_size]
        current_progress = min(i + batch_size, total_chunks)

        try:
            vectorstore.add_documents(batch)
            print(f"✅ 正常入库: {current_progress} / {total_chunks}")
            time.sleep(0.5)  # 🌟 降速：休息半秒，防止被 API 限流

        except Exception as e:
            # ================= 🌟 智能抢救机制 =================
            print(f"⚠️ 批次 {current_progress} 遇到脏数据，启动【逐条抢救模式】...")
            saved_count = 0
            for single_chunk in batch:
                try:
                    vectorstore.add_documents([single_chunk])
                    saved_count += 1
                    time.sleep(0.1)  # 逐条发送也要休息，防止并发太高
                except Exception as inner_e:
                    # 这条就是真正的“老鼠屎”，我们默默丢弃它
                    pass
            print(f"   -> 抢救完毕：成功保住 {saved_count} / {len(batch)} 条数据！")

    print(f"🎉 恭喜！公共理财投顾知识库构建成功！数据已持久化保存在 {persist_dir}")


if __name__ == "__main__":
    build_investment_knowledge_base()