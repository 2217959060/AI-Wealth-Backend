
```markdown
# 🧠 AI-Wealth 智能财务管家系统

基于 **FastAPI + GLM-4** 构建的个人全栈财富管理 Agent 系统。集成 **双模态 Agent（理财投顾 + 理赔顾问）**、**两阶段防捏造管道**、**RAG 向量检索**与**长效记忆体系**，真正实现大模型在金融场景下的高可靠工程化落地。

---

## ✨ 核心亮点

- **🛡️ 两阶段隔离与防捏造拦截**  
  自研两阶段物理隔离管道，彻底解耦 NL2SQL（意图提取）与 NLG（文本生成），在数据缺失时触发物理拦截，将大模型“凭空捏造”幻觉率降至 **0%**。

- **🧠 长效记忆体系 (RAG + Memory)**  
  突破大模型上下文窗口限制：**Redis** 负责短期会话记忆，**ChromaDB** 向量库负责长期财务习惯提炼，赋予 Agent 持续了解用户的“伴随式成长”能力。

- **💬 多模态 Agent 融合**  
  - **理财投顾**：基于 Function Calling，实时查询 MySQL 真实收支并生成可视化 ECharts 图表。  
  - **理赔顾问**：基于 RAG 检索本地保险/理财 PDF 知识库，实现高精度语义问答。

- **⚙️ 全栈工程化落地**  
  FastAPI 高性能 SSE 流式输出、WebSocket 推送导入进度、JWT 无状态鉴权、Docker 微服务容器化设计。

---

## 🛠️ 技术栈

| 类别 | 技术 |
| :--- | :--- |
| 后端框架 | FastAPI, Uvicorn |
| AI 模型 | 智谱 GLM-4 (OpenAI SDK), LangChain |
| 数据库 | MySQL (SQLAlchemy), Redis, ChromaDB |
| 解析引擎 | PyPDF2, pdfplumber, Pandas (支持微信/支付宝账单) |
| 部署 | Docker, Git, Vercel (前端) |

---

## 🗺️ 系统架构图

```mermaid
graph TD
    classDef user fill:#e8f0fe,stroke:#4a6fa5,color:#1a2b4a;
    classDef core fill:#f5f3f0,stroke:#d4c9b8,color:#3a2e1e;
    classDef agent fill:#e6f2f0,stroke:#4a9b8a,color:#1a3a30;
    classDef rag fill:#f2efe8,stroke:#b8a88a,color:#4a3a2a;
    classDef db fill:#e8f0ea,stroke:#7a9a7a,color:#1a3a1a;

    User([用户 / 前端]):::user
    FastAPI[FastAPI 主服务<br/>Uvicorn + SSE]:::core

    subgraph AppLayer[应用核心层]
        Router[路由层<br/>Routers]:::core --> Service[服务层<br/>Services]:::core
        Service --> Agent[AI Agent 调度]:::agent
        Service --> RAG[RAG 检索引擎]:::rag
        Service --> Parser[账单解析器]:::core
    end

    subgraph External[外部依赖]
        MySQL[(MySQL<br/>财务数据)]:::db
        Redis[(Redis<br/>短期记忆)]:::db
        Chroma[(ChromaDB<br/>长期知识库)]:::db
        Zhipu[智谱 GLM-4<br/>大模型]:::agent
    end

    User -->|HTTP / SSE| FastAPI
    FastAPI --> Router
    FastAPI -.->|WebSocket 进度推送| User

    Agent -->|Function Calling| MySQL
    Agent -->|读写缓存| Redis
    RAG -->|向量检索| Chroma
    Agent -->|API 调用| Zhipu
    RAG -.->|增强检索| Zhipu

    FastAPI -->|返回流式响应| User
```

---

## 🚀 快速启动（如何跑起来）

1. **克隆仓库**
   ```bash
   git clone https://github.com/你的用户名/AI-Wealth-Backend.git
   cd AI-Wealth-Backend
   ```

2. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

3. **配置环境变量**  
   复制 `.env.example` 为 `.env`，填入你的智谱 API Key：
   ```text
   ZHIPUAI_API_KEY=你的密钥
   JWT_SECRET_KEY=你的JWT密钥
   ```

4. **启动 MySQL 与 Redis**（本地需提前安装好），然后执行：
   ```bash
   python main.py
   ```

5. 访问 API 文档：`http://127.0.0.1:8000/docs`

---

## 📁 项目目录结构

```
fastapi-backend-demo/
├── main.py                 # 应用入口（核心路由与逻辑）
├── parsers/                # 账单解析引擎（支持微信/支付宝 PDF/CSV）
│   ├── bill_extractor.py
│   └── ai_classifier.py
├── scripts/                # 数据构建工具
│   ├── build_knowledge_db.py   # 构建保险理赔知识库
│   └── build_finance_kb.py     # 构建理财投资知识库
├── data/                   # 静态原始数据（PDF书籍、保单等）
├── .env                    # 敏感环境变量（已忽略，不上传）
└── requirements.txt        # Python 依赖清单
```

---

## 📬 联系与展示

- **项目作者**：[无常](你的GitHub或个人网站链接)
- **在线 Demo**：(如有部署到 Vercel 或服务器，贴链接)
- **简历亮点**：该项目展示了 **Agent 可靠性治理（幻觉拦截）**、**工程化落地能力** 及 **全栈微服务设计**。

> ⚡ 本项目仅用于个人技术展示与面试交流，严禁用于其他用途。

