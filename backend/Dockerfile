FROM python:3.11-slim@sha256:00af38ae2ed311628970782e8a2d7f014d8909dbc63cb97bc0a158187f4db045

WORKDIR /app

# 系统依赖（PostgreSQL 客户端编译与中文 PDF/DOCX 字体）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev util-linux fonts-noto-cjk fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码与数据
COPY app/ ./app/
# 导师治理数据由生产部署以只读文件显式挂载；镜像仅提供空目录，
# 不内置、恢复或自动生成任何导师记录。综述级知识库同属数据目录，
# 由生产 Compose 以只读目录挂载到 /app/data/knowledge。
RUN mkdir -p /app/data
COPY scripts/ ./scripts/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Stable numeric identity lets the host provision 0400 secret files for this
# service without granting group/world read access. Cloud preflight must verify
# the actual Compose bind mount retains uid=10001 and mode=0400.
RUN groupadd --gid 10001 tsingradar \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin tsingradar \
    && mkdir -p /app/private_uploads \
    && chown -R 10001:10001 /app

USER 10001:10001

# 暴露端口
EXPOSE 8000

# Compose 前由独立 migration 服务执行 Alembic；应用进程不迁移数据库。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
