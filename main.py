# FastAPI 核心
from fastapi import FastAPI, HTTPException, Request, Depends, status, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.encoders import jsonable_encoder

# JWT 与 安全
from jose import JWTError, jwt
import bcrypt
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# 工具与配置
import os
import tempfile
import asyncio
import json
import warnings
from datetime import datetime, date, timedelta
from decimal import Decimal, getcontext
from openpyxl import Workbook
from dotenv import load_dotenv
from typing import Optional, Any

# ===================== 导入自定义模块与数据库 =====================
from schemas import BillCreate, BillUpdate, UserCreate, CategoryCreate, BillType, ResponseModel
from utils import validation_exception_handler, http_exception_handler, global_exception_handler
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session
from database import engine, Base, get_db
import models
# ===================== AI接口代码=====================
from pydantic import BaseModel
from openai import OpenAI
import json
from sqlalchemy import func
import redis
# ===================== 新增：RAG 依赖与全局知识库加载 =====================
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import ZhipuAIEmbeddings

# ================= 新增：上传与 WebSocket 依赖 =================
from fastapi import WebSocket, WebSocketDisconnect, UploadFile, File, BackgroundTasks
from fastapi.concurrency import run_in_threadpool
import aiofiles
import uuid

# 引入我们刚才写的解析核武器
from parsers.bill_extractor import UniversalBillParser
from parsers.ai_classifier import run_ai_classification


# 初始化 RAG 向量数据库（全局加载，避免每次请求都读硬盘）
try:
    rag_embeddings = ZhipuAIEmbeddings(model="embedding-2")
    insurance_vectorstore = Chroma(persist_directory="./chroma_db_insurance", embedding_function=rag_embeddings)
    print("✅ RAG 本地保险知识库加载成功！")
except Exception as e:
    print(f"⚠️ RAG 知识库加载失败，请检查是否已运行 build_knowledge_db.py: {e}")

# ===================== 🚀 新增：初始化财务长效习惯向量库 =====================
try:
    financial_vectorstore = Chroma(
        persist_directory="./chroma_db_financial",
        embedding_function=rag_embeddings
    )
    print("✅ 财务长效习惯记忆向量库加载成功！")
except Exception as e:
    print(f"⚠️ 财务长效习惯向量库加载失败: {e}")

# ===================== 🚀 新增：初始化公共理财投顾知识库 =====================
try:
    investment_vectorstore = Chroma(
        persist_directory="./chroma_db_investment",
        embedding_function=rag_embeddings  # 🌟 这里的参数名根据你本地 LangChain 版本对齐，若报错可改为 embedding=rag_embeddings
    )
    print("✅ RAG 本地理财投资知识库加载成功！")
except Exception as e:
    print(f"⚠️ RAG 理财投资知识库加载失败: {e}")

# ===================== 🚀 升级：引入 Redis 接管全局会话记忆 =====================
# 初始化 Redis 客户端 (确保你本地的 Redis 已启动)
# 强制使用 protocol=2 协议，完美兼容 Windows 下的 Redis 5.0
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
redis_client = redis.Redis(host=REDIS_HOST, port=6379, db=0, decode_responses=True, protocol=2)

# 备用内存方案：如果 Redis 没启动，就暂时存在这里，保证应用不崩溃
fallback_memory = {}

def get_chat_history(user_id: int, chat_type: str = "finance") -> list:
    """从 Redis 获取历史聊天记录，带有容错机制"""
    key = f"chat_memory:{chat_type}:{user_id}"
    try:
        data = redis_client.get(key)
        if data:
            return json.loads(data)
        return []
    except redis.exceptions.ConnectionError:
        print("⚠️ 警告：无法连接到 Redis！正在使用临时内存作为备用（重启会丢失）。请检查 Redis 服务是否启动！")
        return fallback_memory.get(key, [])
    except Exception as e:
        print(f"⚠️ Redis 读取发生其他异常: {e}")
        return fallback_memory.get(key, [])

def save_chat_history(user_id: int, chat_history: list, chat_type: str = "finance"):
    """将最新的聊天记录同步写入 Redis，带有容错机制"""
    key = f"chat_memory:{chat_type}:{user_id}"
    # 严格保持最近 6 条（大模型上下文优化）
    recent_history = chat_history[-6:]
    try:
        redis_client.setex(key, timedelta(days=7), json.dumps(recent_history))
    except redis.exceptions.ConnectionError:
        # 如果 Redis 挂了，存入临时内存
        fallback_memory[key] = recent_history
    except Exception as e:
        print(f"⚠️ Redis 写入发生异常: {e}")

# ===================== 全局配置 =====================
getcontext().prec = 10
load_dotenv()


class CustomJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(
            jsonable_encoder(content),
            ensure_ascii=False,
            default=str
        ).encode("utf-8")


# ===================== 核心工具：数据库对象转字典 =====================
def db_to_dict(obj):
    """万能翻译官：把 SQLAlchemy 复杂对象拆解成前端能看懂的普通字典"""
    if isinstance(obj, list):
        return [db_to_dict(item) for item in obj]
    if hasattr(obj, "__table__"):
        return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    return obj


# ===================== 数据库建表魔法 =====================
Base.metadata.create_all(bind=engine)

# ====================== 初始化应用 ======================
app = FastAPI(
    title="AI-Wealth 智能财务管家系统",
    default_response_class=CustomJSONResponse,
    openapi_security_definitions={
        "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
    },
    openapi_security=[{"BearerAuth": []}]
)

app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ===================== JWT 配置 =====================
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "default-dev-key")
if SECRET_KEY == "default-dev-key":
    warnings.warn("⚠️ 生产环境必须配置JWT_SECRET_KEY环境变量，当前使用默认测试密钥！", UserWarning)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7
invalid_tokens = set()
bearer_scheme = HTTPBearer()


def create_access_token(user_id: int):
    to_encode = {"sub": str(user_id)}
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    token = credentials.credentials
    if token in invalid_tokens:
        raise HTTPException(status_code=401, detail="您已退出登录，请重新登录")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Token 格式错误")
        return int(user_id)
    except JWTError as e:
        detail = "Token 已过期，请重新登录" if "expired" in str(e) else "Token 无效，请重新登录"
        raise HTTPException(status_code=401, detail=detail)


# ===================== 跨域配置 =====================
ALLOW_ORIGINS = os.getenv("ALLOW_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 测试阶段允许所有来源，上生产环境时再改
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===================== 🚀 异步任务与 WebSocket 通信塔 =====================

class ConnectionManager:
    """WebSocket 连接管理器，负责给指定前端发消息"""

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]

    async def send_message(self, message: dict, client_id: str):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_text(json.dumps(message, ensure_ascii=False))


ws_manager = ConnectionManager()


@app.websocket("/ws/progress/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """前端连接此接口，监听专属的导入进度"""
    await ws_manager.connect(websocket, client_id)
    try:
        while True:
            await websocket.receive_text()  # 保持心跳连接
    except WebSocketDisconnect:
        ws_manager.disconnect(client_id)


async def process_bill_file_async(file_path: str, user_id: int, client_id: str):
    """后台默默打工的真汉子：解析 -> AI分类 -> 入库"""
    try:
        await ws_manager.send_message({"step": 1, "msg": "📥 文件已接收，正在启动全渠道解析引擎..."}, client_id)

        # 1. 物理解析 (由于是纯计算，放进线程池防止阻塞主线程)
        parser = UniversalBillParser(file_path)
        raw_bills = await run_in_threadpool(parser.parse)

        if not raw_bills:
            await ws_manager.send_message({"step": -1, "msg": "⚠️ 解析完毕，但未提取到任何有效流水数据。"}, client_id)
            return

        await ws_manager.send_message({"step": 2, "msg": f"✅ 物理解析完成！共提取 {len(raw_bills)} 条有效交易。"},
                                      client_id)
        await asyncio.sleep(0.5)  # 给前端留点时间放动画

        # 2. AI 智能打标
        await ws_manager.send_message({"step": 3, "msg": "🤖 正在呼叫大模型进行语义分类（请耐心等待）..."}, client_id)

        # 调用我们的智谱打标函数
        classified_bills = await run_in_threadpool(run_ai_classification, raw_bills, 50)

        await ws_manager.send_message({"step": 4, "msg": "✅ AI 分类完毕，正在将数据拼写入库..."}, client_id)

        # 3. 写入 MySQL 数据库
        db = next(get_db())  # 获取独立的数据库 Session
        saved_count = 0
        for item in classified_bills:
            new_bill = models.Bill(
                user_id=user_id,
                type=item["type"],
                category=item["category"],
                amount=item["amount"],
                remark=item["raw_desc"],
                date=item["date"],
                is_deleted=0
            )
            db.add(new_bill)
            saved_count += 1

        db.commit()

        await ws_manager.send_message({"step": 5, "msg": f"🎉 导入大功告成！成功入库 {saved_count} 条账单！"}, client_id)

    except Exception as e:
        await ws_manager.send_message({"step": -1, "msg": f"❌ 处理发生致命错误: {str(e)}"}, client_id)
    finally:
        # 过河拆桥，删掉刚才上传的临时文件，防止把服务器硬盘塞满
        if os.path.exists(file_path):
            os.remove(file_path)


@app.post("/bill/upload", summary="全渠道账单上传与异步调度")
async def upload_bill_file(
        background_tasks: BackgroundTasks,
        client_id: str,
        file: UploadFile = File(...),
        user_id: int = Depends(get_current_user)
):
    """接收文件并立刻返回，把苦力活扔给 BackgroundTasks"""
    # 将文件保存到本地临时目录
    temp_dir = "./temp_uploads"
    os.makedirs(temp_dir, exist_ok=True)

    # 为了防止文件名冲突，加个 UUID
    safe_filename = f"{uuid.uuid4().hex}_{file.filename}"
    file_path = os.path.join(temp_dir, safe_filename)

    async with aiofiles.open(file_path, 'wb') as out_file:
        content = await file.read()
        await out_file.write(content)

    # 🌟 核心魔法：交代完任务，立刻让主线程收工，后台线程开始接管
    background_tasks.add_task(process_bill_file_async, file_path, user_id, client_id)

    return ResponseModel(code=200, msg="文件已进入后台处理队列")

# ====================== 基础接口 ======================
@app.get("/", summary="首页")
def home():
    return ResponseModel(code=200, msg="后端服务启动成功！🎉", data={"提示": "请访问 /docs 查看接口文档"})


# ====================== 用户模块 ======================
@app.post("/user/register", summary="用户注册")
def register(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="用户名已存在")

    hashed_pwd = bcrypt.hashpw(user.password.encode('utf-8'), bcrypt.gensalt())
    new_user = models.User(username=user.username, password_hash=hashed_pwd.decode('ascii'))

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return ResponseModel(code=200, msg="注册成功", data={"user_id": new_user.id, "username": new_user.username})


@app.post("/user/login", summary="用户登录")
@limiter.limit("3/minute")
def login(user: UserCreate, request: Request, db: Session = Depends(get_db)):
    target_user = db.query(models.User).filter(models.User.username == user.username).first()
    if not target_user or not bcrypt.checkpw(user.password.encode('utf-8'), target_user.password_hash.encode('utf-8')):
        raise HTTPException(status_code=400, detail="用户名或密码错误")

    token = create_access_token(target_user.id)
    return ResponseModel(code=200, msg="登录成功",
                         data={"user_id": target_user.id, "username": target_user.username, "token": token})


@app.post("/user/logout", summary="退出登录")
def logout(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    invalid_tokens.add(credentials.credentials)
    return ResponseModel(code=200, msg="退出登录成功")


# ====================== 账单管理模块 ======================
@app.get("/bill/list", summary="查询账单列表（分页+用户隔离）")
def get_bill_list(page: int = 1, size: int = 10, user_id: int = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    query = db.query(models.Bill).filter(models.Bill.user_id == user_id, models.Bill.is_deleted == 0)

    # 👇 加上这行双重排序（日期倒序，同日期的按录入先后倒序）
    query = query.order_by(models.Bill.date.desc(), models.Bill.id.desc())

    total = query.count()
    start = (page - 1) * size
    bills = query.offset(start).limit(size).all()
    return ResponseModel(code=200, msg="查询成功",
                         data={"total": total, "page": page, "size": size, "list": db_to_dict(bills)})


@app.get("/bill/trash", summary="查询回收站（已删除账单）")
def get_trash_bills(user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    # 👇 修复：原本只有 id 倒序，改成 日期 + id 双重倒序
    deleted_bills = db.query(models.Bill).filter(
        models.Bill.user_id == user_id,
        models.Bill.is_deleted == 1
    ).order_by(models.Bill.date.desc(), models.Bill.id.desc()).all()

    return ResponseModel(code=200, msg="查询成功", data={"list": db_to_dict(deleted_bills)})

@app.get("/bill/detail/{bill_id}", summary="查询账单详情")
def get_bill_detail(bill_id: int, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    bill = db.query(models.Bill).filter(models.Bill.id == bill_id, models.Bill.user_id == user_id,
                                        models.Bill.is_deleted == 0).first()
    if not bill: raise HTTPException(status_code=404, detail="账单不存在")
    # 👇 修复：解析单个对象
    return ResponseModel(code=200, msg="查询成功", data=db_to_dict(bill))


@app.post("/bill/add", summary="添加新账单")
def add_bill(bill: BillCreate, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    new_bill = models.Bill(**bill.model_dump(), user_id=user_id, is_deleted=0)
    db.add(new_bill)
    db.commit()
    db.refresh(new_bill)
    # 👇 修复：解析单个对象
    return ResponseModel(code=200, msg="添加成功", data=db_to_dict(new_bill))


@app.put("/bill/update/{bill_id}", summary="修改账单")
def update_bill(bill_id: int, bill: BillUpdate, user_id: int = Depends(get_current_user),
                db: Session = Depends(get_db)):
    target = db.query(models.Bill).filter(models.Bill.id == bill_id, models.Bill.user_id == user_id,
                                          models.Bill.is_deleted == 0).first()
    if not target: raise HTTPException(status_code=404, detail="账单不存在")

    update_data = bill.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(target, k, v)

    db.commit()
    db.refresh(target)
    # 👇 修复：解析单个对象
    return ResponseModel(code=200, msg="修改成功", data=db_to_dict(target))


@app.delete("/bill/delete/{bill_id}", summary="软删除账单")
def delete_bill(bill_id: int, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    bill = db.query(models.Bill).filter(models.Bill.id == bill_id, models.Bill.user_id == user_id,
                                        models.Bill.is_deleted == 0).first()
    if not bill: raise HTTPException(status_code=404, detail="账单不存在")
    bill.is_deleted = 1
    db.commit()
    return ResponseModel(code=200, msg="删除成功")


@app.delete("/bill/bulk_delete", summary="批量软删除账单 (按日期或清空全部)")
def bulk_delete_bills(
        delete_all: bool = False,
        start_date: Optional[date] = None,  # 👈 将 str 改为 date，FastAPI 会自动拦截非法格式！
        end_date: Optional[date] = None,  # 👈 必须是合法的 YYYY-MM-DD
        user_id: int = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    # 锁定当前用户的有效账单
    query = db.query(models.Bill).filter(
        models.Bill.user_id == user_id,
        models.Bill.is_deleted == 0
    )

    if not delete_all:
        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="若不选择清空全部，必须提供起始和结束日期")

        # 将合法的 date 对象转换回标准的字符串，与数据库字段进行精确比对
        query = query.filter(
            models.Bill.date >= start_date.strftime("%Y-%m-%d"),
            models.Bill.date <= end_date.strftime("%Y-%m-%d")
        )

    # 获取要删除的数据
    bills_to_delete = query.all()
    count = len(bills_to_delete)

    if count == 0:
        return ResponseModel(code=200, msg="所选范围内没有可删除的账单")

    # 执行软删除（移入回收站）
    for b in bills_to_delete:
        b.is_deleted = 1

    db.commit()
    return ResponseModel(code=200, msg=f"成功将 {count} 条账单移入回收站！")

@app.post("/bill/restore/{bill_id}", summary="恢复账单")
def restore_bill(bill_id: int, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    bill = db.query(models.Bill).filter(models.Bill.id == bill_id, models.Bill.user_id == user_id,
                                        models.Bill.is_deleted == 1).first()
    if not bill: raise HTTPException(status_code=404, detail="账单不存在")
    bill.is_deleted = 0
    db.commit()
    db.refresh(bill)
    # 👇 修复：解析单个对象
    return ResponseModel(code=200, msg="恢复成功", data=db_to_dict(bill))

@app.post("/bill/bulk_restore", summary="批量恢复账单 (按日期或恢复全部)")
def bulk_restore_bills(
        restore_all: bool = False,
        start_date: Optional[date] = None,  # 👈 严格限制格式为 YYYY-MM-DD
        end_date: Optional[date] = None,  # 👈 严格限制格式为 YYYY-MM-DD
        user_id: int = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    # 1. 锁定当前用户回收站中（is_deleted == 1）的账单
    query = db.query(models.Bill).filter(
        models.Bill.user_id == user_id,
        models.Bill.is_deleted == 1
    )

    # 2. 如果不是恢复全部，则执行精确的日期范围过滤
    if not restore_all:
        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="若不选择恢复全部，必须提供起始和结束日期")

        # 将合法的 date 对象转回标准字符串，与数据库无缝比对
        query = query.filter(
            models.Bill.date >= start_date.strftime("%Y-%m-%d"),
            models.Bill.date <= end_date.strftime("%Y-%m-%d")
        )

    # 3. 获取即将被捞回的目标数据
    bills_to_restore = query.all()
    count = len(bills_to_restore)

    if count == 0:
        return ResponseModel(code=200, msg="回收站中没有符合条件的账单")

    # 4. 批量修改状态值，将其复活（移出回收站）
    for b in bills_to_restore:
        b.is_deleted = 0

    db.commit()
    return ResponseModel(code=200, msg=f"成功将 {count} 条账单从回收站中完美恢复！")


@app.delete("/bill/bulk_hard_delete", summary="批量彻底删除 (按日期或清空全部)")
def bulk_hard_delete_bills(
        delete_all: bool = False,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        user_id: int = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    # 只针对回收站里的数据
    query = db.query(models.Bill).filter(models.Bill.user_id == user_id, models.Bill.is_deleted == 1)

    if not delete_all:
        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="必须提供日期范围")
        query = query.filter(models.Bill.date >= start_date.strftime("%Y-%m-%d"),
                             models.Bill.date <= end_date.strftime("%Y-%m-%d"))

    count = query.count()
    if count == 0:
        return ResponseModel(code=200, msg="没有可彻底删除的账单")

    query.delete(synchronize_session=False)  # 物理抹除
    db.commit()
    return ResponseModel(code=200, msg=f"成功彻底销毁 {count} 条账单，数据已灰飞烟灭！")


@app.get("/bill/filter", summary="账单多条件筛选")
def filter_bills(type: Optional[BillType] = None, category: Optional[str] = None,
                 user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(models.Bill).filter(models.Bill.user_id == user_id, models.Bill.is_deleted == 0)
    if type: query = query.filter(models.Bill.type == type)
    if category: query = query.filter(models.Bill.category == category)

    # 👇 加上这行双重排序
    query = query.order_by(models.Bill.date.desc(), models.Bill.id.desc())

    return ResponseModel(code=200, msg="筛选成功", data={"list": db_to_dict(query.all())})


# ====================== 统计接口 ======================
@app.get("/bill/stat/total", summary="月度/年度收支统计")
def stat_total(month: Optional[str] = None, year: Optional[str] = None, user_id: int = Depends(get_current_user),
               db: Session = Depends(get_db)):
    if month and year: raise HTTPException(status_code=400, detail="请仅传入 month 或 year 其中一个参数")

    query = db.query(models.Bill).filter(models.Bill.user_id == user_id, models.Bill.is_deleted == 0)
    if month: query = query.filter(models.Bill.date.startswith(month))
    if year: query = query.filter(models.Bill.date.startswith(year))

    filtered = query.all()
    income, expense = Decimal("0"), Decimal("0")
    for b in filtered:
        if b.type == "income":
            income += b.amount
        else:
            expense += b.amount
    return ResponseModel(code=200, msg="统计成功",
                         data={"income": income, "expense": expense, "balance": income - expense})


@app.get("/bill/stat/category", summary="分类占比统计")
def stat_category(month: str, type: BillType, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    data = db.query(models.Bill).filter(models.Bill.user_id == user_id, models.Bill.type == type,
                                        models.Bill.is_deleted == 0).filter(models.Bill.date.startswith(month)).all()
    cate = {}
    for d in data: cate[d.category] = cate.get(d.category, Decimal("0")) + d.amount
    return ResponseModel(code=200, msg="成功", data={"pie": [{"name": k, "value": v} for k, v in cate.items()]})


@app.get("/bill/stat/trend", summary="每日收支趋势")
def stat_trend(month: str, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    data = db.query(models.Bill).filter(models.Bill.user_id == user_id, models.Bill.is_deleted == 0).filter(
        models.Bill.date.startswith(month)).all()
    daily = {}
    for b in data:
        if b.date not in daily:
            daily[b.date] = {"income": Decimal("0"), "expense": Decimal("0")}
        daily[b.date][b.type] += b.amount
    return ResponseModel(code=200, msg="成功", data={"trend": daily})


@app.get("/bill/stat/week", summary="本周收支统计")
def stat_week(user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    today = date.today()
    mon = today - timedelta(days=today.weekday())
    mon_str = mon.strftime("%Y-%m-%d")
    data = db.query(models.Bill).filter(models.Bill.user_id == user_id, models.Bill.date >= mon_str,
                                        models.Bill.is_deleted == 0).all()

    income, expense = Decimal("0"), Decimal("0")
    for b in data:
        if b.type == "income":
            income += b.amount
        else:
            expense += b.amount
    return ResponseModel(code=200, msg="成功", data={"income": income, "expense": expense})


@app.get("/bill/export", summary="导出账单")
def export_bills(background_tasks: BackgroundTasks, user_id: int = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    wb = Workbook()
    ws = wb.active
    ws.append(["收支类型", "分类", "金额", "备注", "日期"])

    # 👇 给它加上排序
    bills = db.query(models.Bill).filter(
        models.Bill.user_id == user_id,
        models.Bill.is_deleted == 0
    ).order_by(models.Bill.date.desc(), models.Bill.id.desc()).all()

    for b in bills:
        ws.append(["收入" if b.type == "income" else "支出", b.category, b.amount, b.remark, b.date])

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        wb.save(tmp.name)
        background_tasks.add_task(os.unlink, tmp.name)
        return FileResponse(tmp.name, filename="账单记录.xlsx")


# ====================== 分类管理接口 ======================
@app.get("/category/list", summary="查询分类")
def get_category_list(type: Optional[BillType] = None, user_id: int = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    query = db.query(models.Category).filter(models.Category.user_id == user_id, models.Category.is_deleted == 0)
    if type: query = query.filter(models.Category.type == type)
    # 👇 修复：解析列表
    return ResponseModel(code=200, msg="成功", data=db_to_dict(query.all()))


@app.post("/category/add", summary="新增分类")
def add_category(cat: CategoryCreate, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    existing_cat = db.query(models.Category).filter(models.Category.user_id == user_id,
                                                    models.Category.name == cat.name, models.Category.type == cat.type,
                                                    models.Category.is_deleted == 0).first()
    if existing_cat:
        raise HTTPException(status_code=400, detail="该分类已存在，请勿重复添加！")

    new_cat = models.Category(**cat.model_dump(), user_id=user_id, is_deleted=0)
    db.add(new_cat)
    db.commit()
    db.refresh(new_cat)
    # 👇 修复：解析单个对象
    return ResponseModel(code=200, msg="添加成功", data=db_to_dict(new_cat))


@app.delete("/category/delete/{category_id}", summary="删除分类")
def delete_category(category_id: int, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    category = db.query(models.Category).filter(models.Category.id == category_id, models.Category.user_id == user_id,
                                                models.Category.is_deleted == 0).first()
    if not category: raise HTTPException(status_code=404, detail="分类不存在")

    has_related_bills = db.query(models.Bill).filter(models.Bill.user_id == user_id,
                                                     models.Bill.category == category.name,
                                                     models.Bill.is_deleted == 0).first()
    if has_related_bills:
        raise HTTPException(status_code=400, detail="该分类下有未删除的账单，无法删除")

    category.is_deleted = 1
    db.commit()
    return ResponseModel(code=200, msg="分类删除成功")


# 1. 换成智谱的门牌号和钥匙
client = OpenAI(
    api_key=os.getenv("ZHIPUAI_API_KEY"),
    base_url="https://open.bigmodel.cn/api/paas/v4/"
)


class AIBillRequest(BaseModel):
    text: str


@app.post("/bill/ai_add", summary="AI 智能记账 (全局思维链 + 全时态支持)")
def add_bill_by_ai(req: AIBillRequest, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    # 1. 合并分类 (保持不变)
    user_categories = db.query(models.Category).filter(models.Category.user_id == user_id,
                                                       models.Category.is_deleted == 0).all()
    user_cat_names = [cat.name for cat in user_categories]
    default_cats = ["餐饮", "交通", "购物", "工资", "娱乐", "其他"]
    all_cats = list(set(user_cat_names + default_cats))
    category_str = "、".join(all_cats)

    # ================= 🚀 终极修复：彻底消灭大模型的日历幻觉 =================
    today = date.today()
    weekday_map = ["一", "二", "三", "四", "五", "六", "日"]
    today_weekday = weekday_map[today.weekday()]

    yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    before_yesterday = (today - timedelta(days=2)).strftime("%Y-%m-%d")
    tomorrow = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    # 预计算：用 Python 绝对精确地算出本周和上周每一天的具体日期！
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(days=7)

    # 生成穷举字典，例如："本周一(2026-06-08), 本周二(2026-06-09)..."
    this_week_str = "，".join(
        [f"本周{weekday_map[i]}({(this_monday + timedelta(days=i)).strftime('%Y-%m-%d')})" for i in range(7)])
    # 生成穷举字典，例如："上周一(2026-06-01), 上周二(2026-06-02)... 上周五(2026-06-05)..."
    last_week_str = "，".join(
        [f"上周{weekday_map[i]}({(last_monday + timedelta(days=i)).strftime('%Y-%m-%d')})" for i in range(7)])

    system_prompt = f"""
    你是一个专业的财务数据提取助手。
    【绝对时间准则】今天是 {today.strftime("%Y-%m-%d")}（星期{today_weekday}）。

    ⚠️ 严禁自己推算日期！遇到时间指代，必须【严格查阅】以下时间对照表：
    - 近期指代：昨天({yesterday})，前天({before_yesterday})，明天({tomorrow})
    - 【本周查表】：{this_week_str}
    - 【上周查表】：{last_week_str}

    【金额计算准则】(极其重要)
    如果包含“AA”、“平摊”等词汇，你必须推算出【用户本人实际承担】的金额！

    请严格且仅输出以下 JSON 格式：
    {{
        "calculation_process": "请在此写下推理：用户提到什么时间？查表后对应哪一天？如果涉及AA，你是怎么计算的？",
        "bills": [
            {{
                "type": "income" 或者是 "expense",
                "category": "请严格从以下列表中选择：[{category_str}]。如果没有合适的，填入 '其他'",
                "amount": 提取出纯数字金额(如果是AA，填入计算后的最终金额),
                "remark": "简短备注",
                "date": "提取记账的具体日期(YYYY-MM-DD)。结合【时间对照表】提取。"
            }}
        ]
    }}
    """

    try:
        response = client.chat.completions.create(
            model="glm-4-flash",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": req.text}
            ],
            response_format={"type": "json_object"}
        )

        ai_result_str = response.choices[0].message.content
        ai_data = json.loads(ai_result_str)

        # 提取 AI 的思考过程
        ai_thoughts = ai_data.get("calculation_process", "AI未提供思考过程")

        saved_bills = []
        bill_list = ai_data.get("bills", [])

        for item in bill_list:
            new_bill = models.Bill(
                user_id=user_id,
                type=item.get("type", "expense"),
                category=item.get("category", "其他"),
                amount=item.get("amount", 0.0),
                remark=item.get("remark", ""),
                date=item.get("date", today.strftime("%Y-%m-%d")),
                is_deleted=0
            )
            db.add(new_bill)
            saved_bills.append(new_bill)

        db.commit()
        for bill in saved_bills:
            db.refresh(bill)

        # ================= 修复 3：直接把 AI 的思考过程显示在 Swagger 的返回值里！ =================
        return ResponseModel(
            code=200,
            msg="AI 记账成功！",
            data={
                "ai_thoughts": ai_thoughts,  # 👈 让你在网页上直接看到它的心路历程
                "saved_bills": db_to_dict(saved_bills)
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 处理失败：{str(e)}")





class AIChatRequest(BaseModel):
    text: str
    tone: str = "毒舌"  # 👈 默认是毒舌，前端可以传“温柔”、“专业”、“阴阳怪气”等



from fastapi import APIRouter



@app.post("/ai/chat", summary="AI 智能财务管家 (流式输出 SSE 终极版)")
def ai_financial_advisor(req: AIChatRequest, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")

    # 🌟 1. 升级：从 Redis 读取历史记忆，而不再是内存字典
    history_messages = get_chat_history(user_id, chat_type="finance")

    # ================= 🌟 新增：从向量库唤醒“长效记忆” =================
    try:
        # 检索该用户最相关的 3 条消费痛点/习惯
        memories = financial_vectorstore.similarity_search(
            "消费习惯 财务痛点",
            k=3,
            filter={"user_id": user_id}
        )
        long_term_memory_str = "\n".join([f"- {m.page_content}" for m in memories])
    except Exception as e:
        print(f"向量库检索失败: {e}")
        long_term_memory_str = "暂无"
    # ===================================================================

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_financial_data",
                "description": "查询指定日期区间内的财务流水数据。可以查收入、支出或结余。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_date": {"type": "string", "description": "起始日期，格式 YYYY-MM-DD"},
                        "end_date": {"type": "string", "description": "结束日期，格式 YYYY-MM-DD"},
                        "query_type": {
                            "type": "string",
                            "enum": ["expense", "income", "all"],
                            "description": "查询类型：expense(仅支出), income(仅收入), all(查询全部收支与结余)"
                        }
                    },
                    "required": ["start_date", "end_date", "query_type"]
                }
            }
        }
    ]

    system_prompt_stage_1 = f"""
        你是意图识别引擎与财务管家。今天是 {today_str}。
        【🚨 用户的专属财务侧写（潜意识记忆）】
        以下是根据该用户历史账单提炼出的行为习惯，在聊天时请【极其自然地】利用这些黑历史来挖苦或建议对方：
        {long_term_memory_str}
        
        【🚨 强制调用工具的触发词库】
        只要用户的输入包含以下【任意一个】词汇或意图，你【必须，立刻，马上】调用 `get_financial_data` 工具，绝不允许直接用文字回答、绝不允许给出通用理财建议：
        1. 财务指标类：收支、收入、支出、花销、消费、结余、账单、明细、花了多少钱。
        2. 动作指令类：分析、对比、画图、展示、统计、总结。
        （例如：用户说“分析本月收支”，你必须调用工具查数据，绝不允许去解释收支的概念！）

        【智能时间推算规则（极其重要）】
        如果用户使用了模糊时间，你必须严格以今天（{today_str}）为基准推算日期：
        - “这两个月”/“最近两个月” = 上个月1号 到 今天。
        - “本月”/“这个月”/“最近一个月” = 本月1号 到 今天。
        - “今年” = 本年1月1号 到 今天。
        绝不允许向用户确认时间，直接默默用推算出的日期调用工具！
        """

    # 🌟 2. 将新问题推入历史，并保持滑动窗口
    history_messages.append({"role": "user", "content": req.text})

    current_messages = [{"role": "system", "content": system_prompt_stage_1}] + history_messages[-6:]

    try:
        response = client.chat.completions.create(
            model="glm-4-flash",
            messages=current_messages,
            tools=tools,
            tool_choice="auto"
        )
        response_message = response.choices[0].message
        function_name = None
        function_args_str = None

        if response_message.tool_calls:
            tool_call = response_message.tool_calls[0]
            function_name = tool_call.function.name
            function_args_str = tool_call.function.arguments
        elif response_message.content and "{" in response_message.content and "start_date" in response_message.content:
            content = response_message.content
            function_name = "get_financial_data"
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            function_args_str = content[json_start:json_end]

        messages_for_second_round = []

        if function_name == "get_financial_data" and function_args_str:
            try:
                function_args = json.loads(function_args_str)
                start_date = function_args.get("start_date")
                end_date = function_args.get("end_date")
                query_type = function_args.get("query_type", "all")

                base_query = db.query(models.Bill).filter(
                    models.Bill.user_id == user_id,
                    models.Bill.date >= start_date,
                    models.Bill.date <= end_date,
                    models.Bill.is_deleted == 0
                )

                if query_type == "expense":
                    base_query = base_query.filter(models.Bill.type == "expense")
                elif query_type == "income":
                    base_query = base_query.filter(models.Bill.type == "income")

                bills = base_query.all()
                total_income = sum(b.amount for b in bills if b.type == "income")
                total_expense = sum(b.amount for b in bills if b.type == "expense")
                balance = total_income - total_expense

                if query_type == "income" and total_income == 0:
                    db_result_str = f"时间区间：{start_date} 至 {end_date}\n🚨 查询结果：这段时间内【没有任何收入记录】！请用纯文本告知用户，严禁画图！"
                elif query_type == "expense" and total_expense == 0:
                    db_result_str = f"时间区间：{start_date} 至 {end_date}\n🚨 查询结果：这段时间内【没有任何支出记录】！请用纯文本告知用户，严禁画图！"
                else:
                    db_result_str = f"时间区间：{start_date} 至 {end_date}\n总收入：{total_income}元\n总支出：{total_expense}元\n净结余：{balance}元\n"

                    if bills:
                        from collections import defaultdict
                        daily_summary = defaultdict(lambda: {"income": 0, "expense": 0})

                    for b in bills:
                        date_str = b.date.strftime("%Y-%m-%d") if hasattr(b.date, 'strftime') else str(b.date)
                        if b.type == "income":
                            daily_summary[date_str]["income"] += float(b.amount)
                        else:
                            daily_summary[date_str]["expense"] += float(b.amount)

                    db_result_str += "\n【每日收支精确汇总】(画图时请严格直接使用以下数据，绝不可漏掉日期或自行计算)：\n"
                    for d in sorted(daily_summary.keys()):
                        db_result_str += f"- {d}: 收入 {daily_summary[d]['income']}元, 支出 {daily_summary[d]['expense']}元\n"

                messages_for_second_round = [
                    {"role": "system", "content": f"""
                你是用户的私人财务管家。今天是 {today_str}。请严格基于提供的最新数据库结果回答。
                
                【🎭 角色扮演绝对红线（Show, Don't Tell）】
                你现在的性格设定是：【{req.tone}】。
                严禁在回复中暴露你的设定！绝对不允许说出“让我用温柔的语气”、“作为毒舌管家”、“我来为你温柔地分析”这种打破沉浸感的废话！直接进入角色，用该语气开始你的表演！
                
                【🚨 防幻觉与上下文污染致命红线】
                1. 【绝对无视历史】：用户的财务数据会随时更新。你【必须且只能】使用下方“当前数据库检索结果”中提供的数据进行计算和分析！【绝对禁止】照抄或参考对话历史中的旧金额、旧日期！
                2. 如果数据库收支均为0或提示无记录，直接用文字回复，【严禁】画图！

                【📊 图表生成强制规范（必须严格遵守）】
                只要你进行收支分析、数据展示、趋势对比，或者用户明确要求画图，你【必须】遵循以下结构输出（先写文字分析，最后附带图表代码）。绝不允许用普通 Markdown 文本表格敷衍！

                (你的分析与吐槽...)

                ```echarts
                {{
                  "title": {{"text": "图表标题"}},
                  "tooltip": {{"trigger": "axis", "axisPointer": {{"type": "shadow"}}}},
                  "legend": {{"left": "left", "top": "top"}},
                  "xAxis": {{"type": "category", "data": ["实际存在的日期1", "实际存在的日期2"]}},
                  "yAxis": {{"type": "value"}},
                  "series": [
                    {{"name": "收入", "type": "bar", "data": [100, 0], "itemStyle": {{"color": "#10b981"}}}},
                    {{"name": "支出", "type": "bar", "data": [50, 80], "itemStyle": {{"color": "#ef4444"}}}}
                  ]
                }}
                ```

                【JSON 校验规范】
                1. 代码必须被 ```echarts 和 ``` 包裹。
                2. 【双色对比铁律】：对比收入和支出时，series 必须包含收入和支出两个对象，颜色必须用绿色和红色。单项则保留一个。
                3. 🚨【数据对齐铁律】：xAxis.data 日期数量必须与 series 每个 data 数组长度【绝对相等】！缺失数据的日子必须写 0 占位！
                                    """},
                    {"role": "user",
                     "content": f"用户问题：{req.text}\n\n当前数据库检索结果：\n{db_result_str}\n\n请以【{req.tone}】的语气给我专业的回复。如果涉及收支对比，文末必须附带 Echarts 代码！"}
                ]

            except Exception as e:
                print(f"🚨 解析工具参数失败: {e}")
                messages_for_second_round = [{"role": "system",
                                              "content": "正常聊天，不能输出 JSON 工具代码！！"}] + history_messages[-6:]

        else:
                # 🌟 修复：把长效记忆也喂给正常聊天的回次！并用极其严厉的 Prompt 封杀它的“AI 声明”
                messages_for_second_round = [
                                                {"role": "system", "content": f"""
                                                              你是用户的私人毒舌管家。今天是 {today_str}。

                                                              【用户深层记忆/黑历史】
                                                              {long_term_memory_str}

                                                              【绝对红线】
                                                              1. 绝不允许说“作为一个人工智能”、“我没有持久记忆”、“我无法记住”这类废话！你现在就是拥有绝佳记忆力的管家！
                                                              2. 必须且只能基于上方的【用户深层记忆】来回答用户关于“习惯、建议、历史”的问题，并狠狠地吐槽。
                                                              """}
                                            ] + history_messages[-6:]

        def generate_stream():
            second_response = client.chat.completions.create(
                model="glm-4-flash",
                messages=messages_for_second_round,
                stream=True
            )
            full_reply = ""
            for chunk in second_response:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_reply += content
                    yield f"data: {json.dumps({'text': content}, ensure_ascii=False)}\n\n"

            # 🌟 3. 升级：流式输出结束后，将 AI 回复合并，同步存入 Redis
            history_messages.append({"role": "assistant", "content": full_reply})
            save_chat_history(user_id, history_messages, chat_type="finance")
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate_stream(), media_type="text/event-stream")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 处理失败：{str(e)}")


from langchain_core.documents import Document


@app.post("/ai/memory/extract", summary="提炼并同步用户财务长效记忆")
def extract_long_term_memory(user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    """定期（或手动）调用此接口，让 AI 审视用户历史账单，提取习惯并存入向量库"""

    # 1. 捞取用户最近 100 条账单（或最近几个月的账单）
    recent_bills = db.query(models.Bill).filter(
        models.Bill.user_id == user_id,
        models.Bill.is_deleted == 0
    ).order_by(models.Bill.date.desc()).limit(100).all()

    if not recent_bills:
        return ResponseModel(code=200, msg="暂无足够账单数据用于分析")

    # 简单拼装一下账单给大模型看
    bills_text = "\n".join([f"{b.date} | {b.type} | {b.category} | ¥{b.amount} | {b.remark}" for b in recent_bills])

    # 2. 让大模型做“侧写师”，提炼财务画像
    prompt = f"""
    你是顶级的财务分析师。请分析以下用户最近的账单记录，提炼出该用户在消费、收入上的【核心习惯】与【致命痛点】。

    用户账单记录：
    {bills_text}

    【要求】
    1. 语气冷酷客观。
    2. 提取出 3 到 5 条核心结论（例如：“高频在周末产生大额娱乐支出”、“对‘餐饮’类别的预算控制极差”、“有稳定的兼职收入但缺乏储蓄习惯”等）。
    3. 直接输出结论，每条结论一段话，不要任何多余的寒暄或格式。
    """

    try:
        response = client.chat.completions.create(
            model="glm-4-flash",
            messages=[{"role": "user", "content": prompt}]
        )
        insights = response.choices[0].message.content.split('\n')

        # 3. 清洗并存入向量数据库 ChromaDB
        docs_to_store = []
        for insight in insights:
            insight = insight.strip()
            if insight and len(insight) > 5:  # 过滤掉空行或废话
                # 把提炼出的每一条习惯，变成带 user_id 标签的文档存起来
                docs_to_store.append(Document(
                    page_content=insight,
                    metadata={"user_id": user_id, "type": "financial_habit"}
                ))

        if docs_to_store:
            # 存入我们上次定义好的 financial_vectorstore
            financial_vectorstore.add_documents(docs_to_store)

        return ResponseModel(code=200, msg="长效记忆提炼并同步成功！",
                             data={"insights": [d.page_content for d in docs_to_store]})

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"长效记忆提炼失败：{str(e)}")
@app.get("/ai/chat/history", summary="获取历史聊天记录")
def get_ai_chat_history(chat_type: str = "finance", user_id: int = Depends(get_current_user)):
    # 直接调用我们之前写好的 Redis 读取函数
    history = get_chat_history(user_id, chat_type=chat_type)

    # 过滤掉 system 提示词（如果有的话），只返回 user 和 assistant 的对话给前端
    display_history = [msg for msg in history if msg.get("role") != "system"]

    return ResponseModel(code=200, msg="获取历史记录成功", data={"history": display_history})

# ===================== 新增：AI 保险理赔顾问专属接口 =====================
class AIPolicyRequest(BaseModel):
    text: str

@app.delete("/ai/chat/history", summary="清空用户的短期聊天记忆")
def clear_ai_chat_history(chat_type: str = "finance", user_id: int = Depends(get_current_user)):
    """抹除 Redis 中的对话上下文，实现真正的 New Chat"""
    key = f"chat_memory:{chat_type}:{user_id}"
    try:
        redis_client.delete(key) # 物理删除 Redis 里的这个键
        return ResponseModel(code=200, msg="短期记忆已清空")
    except redis.exceptions.ConnectionError:
        # 如果 Redis 没开，清空备用内存里的数据
        if key in fallback_memory:
            del fallback_memory[key]
        return ResponseModel(code=200, msg="临时记忆已清空")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清空记忆失败：{str(e)}")

@app.post("/ai/ask_policy", summary="AI 保险理赔顾问 (流式输出 SSE)")
def ai_claims_advisor(req: AIChatRequest, user_id: int = Depends(get_current_user)):
    # 🌟 1. 从 Redis 读取该用户的历史记忆（理赔专用）
    history_messages = get_chat_history(user_id, chat_type="rag")

    # 🌟 2. 将用户当前问题追加到历史中（准备送入模型）
    history_messages.append({"role": "user", "content": req.text})

    # 理赔顾问的专属系统提示词（含今日日期）
    today_str = date.today().strftime("%Y-%m-%d")
    system_prompt = f"你是专业的保险理赔顾问。今天是 {today_str}。如果用户询问理赔条件、保险条款等问题，请根据你的知识解答。请注意使用 Markdown 格式（如加粗、列表）让排版更清晰。"

    # 滑动窗口：保留最近 6 轮对话 + 系统提示词
    messages = [{"role": "system", "content": system_prompt}] + history_messages[-6:]

    try:
        def generate_stream():
            response = client.chat.completions.create(
                model="glm-4-flash",
                messages=messages,
                stream=True  # 开启流式
            )
            full_reply = ""
            for chunk in response:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_reply += content
                    yield f"data: {json.dumps({'text': content}, ensure_ascii=False)}\n\n"

            # 🌟 3. 流式输出结束后，将 AI 回复存入 Redis
            history_messages.append({"role": "assistant", "content": full_reply})
            save_chat_history(user_id, history_messages, chat_type="rag")
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate_stream(), media_type="text/event-stream")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 理赔分析失败：{str(e)}")


@app.post("/ai/invest/chat", summary="终极缝合：Redis记忆 + 冷热数据双刀流理财顾问（流式输出）")
def invest_advisor_chat(
        req: AIChatRequest,  # 🌟 完美复用你原有的请求体模型
        user_id: int = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """
    真正的智能投顾大脑：
    1. 从 Redis 读取历史记忆，保持多轮对话连续性
    2. 自动统计 SQLite 中用户当月的真实收支数据
    3. 从 ChromaDB 中检索晨星研报与理财圣经知识
    4. 流式输出结束后，自动将 AI 的回答存回 Redis
    """
    global investment_vectorstore

    # 🌟 1. 从 Redis 读取该用户的历史记忆（专门开辟 investment 通道，与保单理赔隔离）
    history_messages = get_chat_history(user_id, chat_type="investment")

    # 🌟 2. 将用户当前问题追加到历史中
    history_messages.append({"role": "user", "content": req.text})

    # 3. 📊 提取用户当前月份的真实财务数据（冷数据）
    current_month = datetime.now().strftime("%Y-%m")

    total_income = db.query(func.sum(models.Bill.amount)).filter(
        models.Bill.user_id == user_id,
        models.Bill.is_deleted == 0,
        models.Bill.type == "income",
        models.Bill.date.like(f"{current_month}%")
    ).scalar() or 0.0

    total_expense = db.query(func.sum(models.Bill.amount)).filter(
        models.Bill.user_id == user_id,
        models.Bill.is_deleted == 0,
        models.Bill.type == "expense",
        models.Bill.date.like(f"{current_month}%")
    ).scalar() or 0.0

    net_balance = total_income - total_expense
    savings_rate = (net_balance / total_income * 100) if total_income > 0 else 0.0

    user_profile_str = (
        f"【用户当前真实财务画像 ({current_month})】\n"
        f"- 本月总收入：{total_income:.2f} 元\n"
        f"- 本月总支出：{total_expense:.2f} 元\n"
        f"- 本月净结余：{net_balance:.2f} 元\n"
        f"- 当前储蓄率：{savings_rate:.2f}%\n"
    )

    # 4. 🔍 检索公共理财知识库（RAG 热行动）
    rag_context = ""
    if investment_vectorstore:
        docs = investment_vectorstore.similarity_search(req.text, k=4)
        rag_context = "\n\n".join([f"[{i + 1}] {doc.page_content}" for i, doc in enumerate(docs)])
    else:
        rag_context = "（暂无本地理财书籍知识库，请根据通用理财常识回答）"

    # 5. 🧠 构筑大厂级融合 System Prompt（将冷数据与热知识作为背景注入系统）
    today_str = datetime.now().strftime("%Y-%m-%d")
    system_prompt = f"""
你是系统内置的【AI 顶级财富顾问】。今天是 {today_str}。你的目标是将高深的理财理论与用户的实际财务状况相结合，提供个性化的个人资产配置建议。

请严格基于以下两部分提供的信息进行推导和回答：

{user_profile_str}

【📚 本地理财指南与晨星研报检索结果】
{rag_context}

【🧠 行为守则与金牌顾问红线】
1. 必须将用户的真实数据（如结余、储蓄率）与检索到的理论（如《小狗钱钱》的先支付自己原则、《FIRE》的4%退休法则、4321资产配置法则、晨星主动/被动基金晴雨表）深度缝合！
2. 如果用户本月入不敷出（净结余为负）或储蓄率极低，必须优先警告其“拿铁因子”漏洞，要求其优先清偿高息负债。
3. 如果用户结余充足，请帮其算出具体的定投金额建议（例如结余的50%），并根据晨星研报，向其阐述在当前市场环境下为什么定投低估值宽基指数基金胜率更高。
4. 语气要极其专业、严谨、充满远见且温暖贴心，多使用具体的数字和计算公式。
5. 绝对不允许说出“根据提供的数据”或“根据检索到的文档”等出戏的连词，直接以专业老练的口吻切入作答。
"""

    # 🌟 6. 滑动窗口拼接：核心 System Prompt + 最近 6 轮 Redis 对话历史
    messages = [{"role": "system", "content": system_prompt}] + history_messages[-6:]

    # 7. 🚀 呼叫大模型，以流式传输（SSE）返回结果
    try:
        response = client.chat.completions.create(
            model="glm-4",
            messages=messages,
            stream=True
        )

        def event_generator():
            full_reply = ""
            for chunk in response:
                if chunk.choices[0].delta.content:
                    text_chunk = chunk.choices[0].delta.content
                    full_reply += text_chunk
                    yield f"data: {json.dumps({'text': text_chunk}, ensure_ascii=False)}\n\n"

            # 🌟 8. 流式输出结束后，将 AI 完整的回复追加并存入 Redis，确保多轮记忆不断档
            history_messages.append({"role": "assistant", "content": full_reply})
            save_chat_history(user_id, history_messages, chat_type="investment")
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    except Exception as e:
        return ResponseModel(code=500, msg=f"智能投顾大脑连接失败: {str(e)}", data=None)

@app.get("/bill/export_all", summary="获取全量账单用于前端 Web Worker 导出")
def get_all_bills_for_export(user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    # 极速拉取当前用户所有未删除的账单，按时间倒序
    bills = db.query(models.Bill).filter(
        models.Bill.user_id == user_id,
        models.Bill.is_deleted == 0
    ).order_by(models.Bill.date.desc()).all()

    # 瘦身：只挑前端 Excel 需要的字段，减小网络传输体积
    result = [
        {
            # 🌟 增加容错：判断它是不是时间对象，如果不是，直接转成字符串即可
            "date": b.date.strftime("%Y-%m-%d") if hasattr(b.date, 'strftime') else str(b.date),
            "type": b.type,
            "category": b.category,
            "amount": float(b.amount),
            "remark": b.remark
        }
        for b in bills
    ]

    return {"code": 200, "message": "success", "data": result}
# ====================== 启动 ======================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)