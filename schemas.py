from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any
from enum import Enum
from decimal import Decimal
from datetime import datetime

# ====================== 枚举类型 ======================
class BillType(str, Enum):
    expense = "expense"  # 支出
    income = "income"    # 收入

# ====================== 统一响应模型 ======================
class ResponseModel(BaseModel):
    code: int
    msg: str
    data: Optional[Any] = None

    class Config:
        from_attributes = True  # Pydantic V2 写法

# ====================== 账单模块 ======================
class BillCreate(BaseModel):
    type: BillType = Field(..., description="收支类型，只能是income/expense")
    category: str = Field(min_length=1, max_length=20, description="分类不能为空，长度1-20")
    amount: Decimal = Field(gt=0, description="金额必须大于0")
    remark: Optional[str] = Field(None, max_length=100, description="备注最多100字")
    date: str = Field(..., description="账单日期，格式YYYY-MM-DD")

    # 完全保留原版的日期严格校验
    @field_validator('date')
    def date_must_be_valid(cls, value):
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            raise ValueError("日期格式错误！请使用 YYYY-MM-DD 格式（如 2026-04-23）")

class BillUpdate(BaseModel):
    type: Optional[BillType] = Field(None, description="收支类型，只能是income/expense")
    category: Optional[str] = Field(None, min_length=1, max_length=20, description="分类不能为空，长度1-20")
    amount: Optional[Decimal] = Field(None, gt=0, description="金额必须大于0")
    remark: Optional[str] = Field(None, max_length=100, description="备注最多100字")
    date: Optional[str] = Field(None, description="账单日期，格式YYYY-MM-DD")

    @field_validator('date')
    def date_must_be_valid(cls, value):
        if value is None or value == "":
            return value
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            raise ValueError("日期格式错误！请使用 YYYY-MM-DD 格式（如 2026-04-23）")

# ====================== 分类管理模块 ======================
class CategoryCreate(BaseModel):
    name: str  # 分类名称
    type: BillType  # 分类类型：income/expense

class Category(CategoryCreate):
    id: int

# ====================== 用户模块 ======================
class UserCreate(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")

    # 完全保留原版的密码强度校验
    @field_validator('password')
    def password_must_be_strong(cls, value):
        if len(value) < 6:
            raise ValueError("密码长度不能少于 6 位！")
        return value

class User(BaseModel):
    id: int
    username: str

    class Config:
        from_attributes = True  # 修复过时的 orm_mode = True


# ====================== 面试系统模块 ======================

# 1. 开启一场新面试的请求参数
class InterviewStartRequest(BaseModel):
    # 偷偷夹带私货：默认岗位填我正在找的 Python 后端开发！
    job_title: str = Field(default="Python后端开发实习生", description="面试岗位")
    role_type: str = Field(default="专业", description="面试官的性格：专业、毒舌、压力测试")

# 2. 面试过程中的对话请求参数
class InterviewChatRequest(BaseModel):
    session_id: int = Field(..., description="当前面试的房间号(数据库ID)")
    user_message: str = Field(..., description="候选人的回答内容")

# 3. 核心！限制 AI 输出格式的模型（Function Calling 会用到它）
class InterviewFeedback(BaseModel):
    logic_score: int = Field(..., ge=0, le=100, description="逻辑清晰度得分(0-100)")
    tech_score: int = Field(..., ge=0, le=100, description="技术准确度得分(0-100)")
    feedback: str = Field(..., description="给候选人的犀利点评与改进建议")
    next_question: str = Field(..., description="根据候选人的回答，生成的下一个面试问题")