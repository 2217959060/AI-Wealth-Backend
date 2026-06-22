import os
import re
from dotenv import load_dotenv   # 👈 新增这一行
load_dotenv()                    # 👈 新增这一行


from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import ZhipuAIEmbeddings

# 1. 填入你的智谱 API Key



def build_insurance_vector_db(pdf_path: str, db_persist_dir: str):
    print(f"📄 正在读取保险文档: {pdf_path} ...")

    # ================= 核心 1：文档加载 =================
    loader = PyPDFLoader(pdf_path)
    pages = loader.load()
    print(f"✅ 成功加载文档，共 {len(pages)} 页。")


    # ================= 核心 2：文本切片与暴力清洗 (Chunking & Cleaning) =================
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，"]
    )
    raw_docs = text_splitter.split_documents(pages)

    valid_docs = []
    for doc in raw_docs:
        cleaned_text = doc.page_content
        # 1. 剔除所有肉眼不可见的幽灵控制字符 (PDF 的万恶之源)
        cleaned_text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', cleaned_text)
        # 2. 将多个连续的空格或换行替换为一个空格
        cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
        # 3. 去除首尾空格
        cleaned_text = cleaned_text.strip()

        # 严格把关：只要长度大于 10 个字符的有意义文本
        if cleaned_text and len(cleaned_text) > 10:
            doc.page_content = cleaned_text
            valid_docs.append(doc)

    print(f"🔪 文档切片与深度清洗完成：原本 {len(raw_docs)} 块，保留了 {len(valid_docs)} 块高质量文本。")

    # ================= 核心 3：带容错的向量化与存储 (Robust Embedding) =================
    print("🧠 正在调用智谱 AI 将文本块转化为多维向量...")
    embeddings = ZhipuAIEmbeddings(model="embedding-2")
    vectorstore = Chroma(embedding_function=embeddings, persist_directory=db_persist_dir)

    # 缩小批次到 20，并加入“探雷器”容错机制
    batch_size = 20
    for i in range(0, len(valid_docs), batch_size):
        batch_docs = valid_docs[i: i + batch_size]
        print(f"⏳ 正在提交批次: 第 {i + 1} 到 {min(i + batch_size, len(valid_docs))} 个文本块...")
        try:
            # 尝试整批提交
            vectorstore.add_documents(batch_docs)
        except Exception as e:
            print(f"⚠️ 批次提交失败，触发单条排查模式...")
            # 如果这批数据里有一条毒数据，我们就逐条提交，揪出内鬼！
            for single_doc in batch_docs:
                try:
                    vectorstore.add_documents([single_doc])
                except Exception as inner_e:
                    print(f"🚨 剔除了一条有毒文本：{single_doc.page_content[:30]}...")
                    continue  # 跳过毒文本，继续下一条

    print(f"🎉 知识库构建成功！已保存在本地目录: {db_persist_dir}")


if __name__ == "__main__":
    # 假设你的保险 PDF 叫 insurance_policy.pdf
    pdf_file = "../data/insurance_policy.pdf"

    # 给数据库起个名字所在的文件夹
    db_dir = "../chroma_db_insurance"

    build_insurance_vector_db(pdf_file, db_dir)