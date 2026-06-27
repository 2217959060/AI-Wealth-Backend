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

![系统架构图](https://raw.githubusercontent.com/2217959060/AI-Wealth-Backend/main/images/architecture.png)

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

## 🐳 Docker 一键部署（推荐）

> 这是给面试官/使用者最快捷的体验方式：**一行命令跑通全套服务**。

### 前置条件

- 安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)（Windows/Mac）或 Docker Engine（Linux）
- 确保 Docker Compose 已安装（新版 Docker Desktop 自带）

### 快速启动

1. **克隆仓库并进入目录**

   ```bash
   git clone https://github.com/你的用户名/AI-Wealth-Backend.git
   cd AI-Wealth-Backend
   ```

2. **配置环境变量**

   在项目根目录创建 `.env` 文件（参考 `.env.example`），填入：

   ```env
   ZHIPUAI_API_KEY=你的智谱API密钥
   JWT_SECRET_KEY=你的JWT密钥（建议32位以上随机字符串）
   ```

3. **一键启动所有服务**

   ```bash
   docker-compose up -d
   ```

   该命令会自动拉取并启动：
   - MySQL 8.0（数据库）
   - Redis 7.0（会话缓存）
   - AI-Wealth 后端服务（你的 Docker Hub 镜像）

4. **验证服务**

   访问 API 文档： [http://localhost:8000/docs](http://localhost:8000/docs)

   注册新用户 → 登录获取 Token → 体验 AI 记账与财务分析。

5. **停止服务**

   ```bash
   docker-compose down
   ```

### 环境变量说明

| 变量名 | 说明 | 是否必填 | 示例 |
|--------|------|----------|------|
| `ZHIPUAI_API_KEY` | 智谱 AI 的 API Key | ✅ 必填 | `abc123...` |
| `JWT_SECRET_KEY` | JWT 加密密钥 | ⚠️ 建议修改 | `your-secret-key` |
| `DATABASE_URL` | MySQL 连接串（Compose 已注入） | 无需手动设置 | — |
| `REDIS_HOST` | Redis 主机地址（Compose 已注入） | 无需手动设置 | — |
| `ALLOW_ORIGINS` | 前端跨域白名单 | 可选 | `http://localhost:3000` |

### 备选方案：仅运行后端镜像（需外部依赖）

> 如果你已经**本地安装好了 MySQL 和 Redis**，不想用 Docker Compose 拉起全套服务，也可以单独运行后端镜像。

```bash
# 1. 拉取镜像
docker pull lossn/ai-wealth-backend:latest

# 2. 运行容器（必须传入数据库和 Redis 地址）
docker run -d -p 8000:8000 \
  -e ZHIPUAI_API_KEY=你的智谱API密钥 \
  -e JWT_SECRET_KEY=你的JWT密钥 \
  -e DATABASE_URL=mysql+pymysql://root:123456@host.docker.internal:3306/my_bill_db \
  -e REDIS_HOST=host.docker.internal \
  --name ai-wealth-backend \
  lossn/ai-wealth-backend:latest
```

> ⚠️ **注意**：  
> - 该命令中的数据库密码 `123456` 是项目默认配置，请根据你本地的 MySQL 密码自行修改。  
> - `host.docker.internal` 仅适用于 Windows/Mac 的 Docker Desktop，Linux 用户请改用 `--network host` 或直接使用上面的 `docker-compose` 方案。

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

