# 🧠 AI-Wealth 智能财务管家系统

基于 **FastAPI + GLM** 构建的个人全栈财富管理系统。三条 AI 线深度不同、名实对齐：

- **理财管家**：Tool-Augmented（`query_bills` / `aggregate_stats`，`max_tool_rounds=2`，含一次失败重规划）+ 程序级防捏造闸门 + `evals/` 确定性回归  
- **理赔顾问**：保险条款真 RAG（检索 → grounded 生成 → SSE `sources`）  
- **理财投顾**：月度账单画像 + 投资知识库浅层 RAG  

习惯库为长期侧写（profile 注入），**不是**问答 RAG。编排为自研有限步工具循环（含失败重规划），未引入图编排框架。


---

## ✨ 核心亮点

- **🛡️ 程序级防捏造闸门（理财）**  
  Tool 查库 → NLG；空结果剥除 echarts；图表 `series[].data` 与当次 tool 汇总对账；`evals/run_finance_checks.py` 可一键回归。

- **🔁 编排失败可恢复、行为可回归**  
  工具参数错误 / 日期非法 / 查库异常 → 回灌重规划指令，复用下一轮修正参数（**不增加 LLM 调用次数**）；仍失败则降级拒答、禁止编数字，全程 `tool_trace` 可回放。`evals/run_finance_checks.py` 中 6 条用例专门测编排行为（双工具、合并对账、失败重规划、两种终止条件），报告在 `evals/reports/` 分组留档。

- **🧠 记忆分层**  
  Redis 短期会话；Chroma 习惯侧写（profile 注入，非问答 RAG）。

- **💬 三条线名实对齐**  
  - **理财管家**：有限步双工具编排（`max_tool_rounds=2`）+ 一次失败重规划 + SSE `tool_trace`  
  - **理赔顾问**：保险条款真 RAG + SSE `sources`  
  - **理财投顾**：账单画像 + 投资知识库浅层 RAG  

- **⚙️ 工程化**  
  FastAPI SSE、WebSocket 导入进度、JWT、Docker Compose、确定性回归脚本。

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

6. **（可选）跑一遍确定性回归**  
   不调用大模型 / 数据库 / 向量库，把外部依赖换成 Fake，几秒完成、结果可复现：
   ```bash
   python evals/run_finance_checks.py      # 13/13（编排行为 6/6 + 闸门校验 7/7）
   python evals/run_policy_guards.py       # 4/4
   python evals/run_e1_e4_checks.py       # 5/5
   ```
   每次运行会在 `evals/reports/` 生成带时间戳的 JSON 报告与 `_latest.json`；用例清单见 `evals/cases_finance.jsonl`、`evals/cases_policy.jsonl`。
   > `evals/run_policy_retrieve.py` 是检索冒烟脚本，**需要调用收费的 embedding-2**（账户余额不足会失败），且它只打印召回结果、不做断言打分。

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

### 🪟 Windows 用户专属：一键启动脚本

如果你是 Windows 用户，且希望**全自动启动前端 + 后端**，可以使用项目根目录下的 `start.bat` 脚本：

1. **克隆前端仓库**（与后端放在同一级目录下）：
   ```bash
   git clone https://github.com/2217959060/AI-Wealth-Frontend.git
   ```
   确保目录结构如下：
   ```
   D:\your-project\
   ├── fastapi-backend-demo\      # 后端仓库（包含 start.bat）
   └── ai-wealth-frontend\        # 前端仓库（与后端平级）
   ```

2. **双击运行 `start.bat`**：
   - 脚本会自动启动后端（Docker Compose）和前端（Vite 开发服务器）
   - 等待几秒后，浏览器会自动打开 `http://localhost:5173`

3. **注册账号并登录**，开始体验AI Wealth功能。

> 💡 **停止服务**：前端按 `Ctrl+C` 停止，后端执行 `docker-compose down` 停止容器。

### 环境变量说明

| 变量名 | 说明 | 是否必填 | 示例 |
|--------|------|----------|------|
| `ZHIPUAI_API_KEY` | 智谱 AI 的 API Key | ✅ 必填 | `abc123...` |
| `JWT_SECRET_KEY` | JWT 加密密钥 | ⚠️ 建议修改 | `your-secret-key` |
| `DATABASE_URL` | MySQL 连接串（Compose 已注入） | 无需手动设置 | — |
| `REDIS_HOST` | Redis 主机地址（Compose 已注入） | 无需手动设置 | — |
| `ALLOW_ORIGINS` | 前端跨域白名单，逗号分隔；本地 `localhost`/`127.0.0.1` 任意端口默认放行 | 可选 | `http://localhost:5173,https://your-frontend.vercel.app` |

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
├── main.py                     # 应用入口（核心路由与 SSE）
├── finance_agent.py            # 理财管家有限步工具循环（含失败重规划）
├── finance_guards.py           # 参数/日期校验 + 程序级输出闸门
├── policy_rag.py               # 理赔条款检索、grounding 与拒答
├── invest_tools.py             # 投顾只读品类汇总工具
├── memory_profile.py           # 长期财务侧写（profile 注入）
├── llm_config.py               # 聊天 / Embedding 模型名集中配置
├── parsers/                    # 账单解析引擎（支持微信/支付宝 PDF/CSV）
│   ├── bill_extractor.py
│   └── ai_classifier.py
├── scripts/                    # 数据构建工具
│   ├── build_knowledge_db.py   # 构建保险理赔知识库
│   └── build_finance_kb.py     # 构建理财投资知识库
├── evals/                      # 确定性回归（不依赖大模型，一键跑）
│   ├── cases_finance.jsonl     # 理财用例清单（13 条）
│   ├── cases_policy.jsonl      # 理赔问句清单（8 条）
│   ├── run_finance_checks.py   # 13 条：闸门校验 7 + 编排行为 6
│   ├── run_policy_guards.py    # 4 条：拒答闸门
│   ├── run_e1_e4_checks.py     # 5 条：工具函数 / 记忆降级
│   ├── run_policy_retrieve.py  # 检索冒烟（需收费 embedding-2）
│   └── reports/                # 每次运行自动留档的 JSON 报告
├── data/                       # 静态原始数据（PDF书籍、保单等）
├── .env                        # 敏感环境变量（已忽略，不上传）
└── requirements.txt            # Python 依赖清单
```

---

## 🔗 相关仓库

- **前端仓库**：[AI-Wealth-Fronted](https://github.com/2217959060/AI-Wealth-Frontend)

---

## 📬 联系与展示

- **项目作者**：[无常](https://github.com/2217959060)
- **简历亮点**：该项目展示了 **Agent 可靠性治理（幻觉拦截）**、**工程化落地能力** 及 **全栈微服务设计**。

> ⚡ 本项目仅用于个人技术展示与面试交流，严禁用于其他用途。

