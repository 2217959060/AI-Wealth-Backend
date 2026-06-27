from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# 从环境变量读取，如果没有则用默认值（兼容本地开发）
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:123456@localhost:3306/my_bill_db?charset=utf8mb4"
)

# 创建发动机
engine = create_engine(SQLALCHEMY_DATABASE_URL, echo=False)  # echo=True 可以让你在终端看到它翻译的 SQL 语句，现在先关掉保持清爽

# 创建数据库会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 创建基本映射类，后面的数据表都要继承它
Base = declarative_base()

# 获取数据库会话的依赖函数（一会要在 main.py 里用到）
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()