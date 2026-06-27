# 使用 Python 3.12 官方镜像作为基础
FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量：强制 Python 实时输出日志
ENV PYTHONUNBUFFERED=1

# 先复制 requirements.txt 单独安装依赖（利用 Docker 缓存加速）
COPY requirements.txt .

# 安装依赖（加 --no-cache-dir 减小镜像体积）
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制项目所有代码到容器内
COPY . .

# 暴露 8000 端口（FastAPI 默认端口）
EXPOSE 8000

# 启动命令：使用 uvicorn 运行 main.py
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]