from sqlalchemy import Column, Integer, String, DECIMAL, Text # 加上 Text
from database import Base

# 用户表
class User(Base):
    __tablename__ = "users"  # 对应 MySQL 里的表名

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    password_hash = Column(String(100))

# 账单表
class Bill(Base):
    __tablename__ = "bills"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    type = Column(String(20))       # income 或 expense
    category = Column(String(50))   # 比如：餐饮、交通
    amount = Column(DECIMAL(10, 2)) # 金融级精度
    remark = Column(String(100), nullable=True)
    date = Column(String(20), index=True) # YYYY-MM-DD 格式
    is_deleted = Column(Integer, default=0) # 0正常，1已软删除

# 分类表
class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50))
    type = Column(String(20))
    user_id = Column(Integer, index=True)
    is_deleted = Column(Integer, default=0)

class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    role_type = Column(String(50))         # 面试官性格：如毒舌、温柔
    job_title = Column(String(100))        # 目标岗位
    chat_history = Column(Text)            # 存长对话（面试全记录）
    scores = Column(String(500))           # 存评分结果
    is_active = Column(Integer, default=1) # 1:正在面试, 0:面试结束