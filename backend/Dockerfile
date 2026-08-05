FROM python:3.11-slim

WORKDIR /app

# 系统依赖（PostgreSQL 客户端编译用）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && rm -rf /var/lib/apt/lists/*

# 先装依赖（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码与数据
COPY app/ ./app/
COPY data/ ./data/
COPY scripts/ ./scripts/
COPY alembic/ ./alembic/
COPY alembic.ini .

# 暴露端口
EXPOSE 8000

# 启动命令（生产期用 gunicorn 多 worker）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
