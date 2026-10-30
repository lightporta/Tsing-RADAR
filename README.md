<div align="center">

# 🛰️ Tsing-RADAR 清研寻师雷达

**Research Advisor Dimension Analysis Radar**

清华大学"清小搭"智能体广场 · 导师智能匹配智能体

从"被动求职"到"主动寻找学术合伙人"

![Version](https://img.shields.io/badge/version-2.2.0-409EFF?style=flat-square)
![Vue](https://img.shields.io/badge/Vue-3.5-42b883?style=flat-square)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square)
![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178c6?style=flat-square)
![License](https://img.shields.io/badge/license-Internal-orange?style=flat-square)

</div>

---

## 📖 项目简介

Tsing-RADAR 通过持久化访谈收集学生需求，在学生确认画像后执行**硬约束过滤、词法/概念召回和证据化多目标排序**。Web 与清小搭兼容接口共享业务服务，结果同时呈现适配、证据覆盖、置信度和待核实问题。

当前是本地模拟验证版本：示例配置使用规则访谈和三条明确标注的合成导师，真实模型 API、正式导师数据与生产公网均需后续接入和验收。旧雷达重叠算法保留作历史展示工具，不是当前推荐的排序依据。

### ✨ 核心能力

| 模块 | 说明 |
| :--- | :--- |
| 🎯 **证据化匹配** | 主题 / 研究方式 / 指导方式 / 生涯 / 创新 / 机会六目标排序 |
| 💬 **动态访谈** | 服务端状态机、可编辑画像、硬约束澄清和显式确认 |
| 📊 **结果解释与比较** | 适配与证据分开展示；无来源的指标不补假值 |
| 📄 **私有文档** | 上传 PDF/DOCX，按明确输入生成简历和匹配报告，授权下载 |
| 📢 **招募与行动记录** | 投稿需审核；仅创建站内投递，不发送邮件或联系第三方 |
| 🔄 **反馈与评估** | 收集偏好反馈；训练受数据就绪门限制，当前不训练排序模型 |

---

## 🖼 界面预览

桌面端保留“访谈 / 推荐列表 / 结果解释”的三栏工作台，移动端切换为分区浏览。模拟模式在页面顶部和结果区明确标注；确认画像前不生成推荐。导师资源库独立检索公开资源，个人信息页负责简历资料与私有文件。

---

## 🚀 快速开始（部署与打开方案）

提供三种部署方式，按需选择。

### 📦 方式一：本地开发模式（最简，推荐首次体验）

> 示例配置使用 SQLite + 本地私有文件 + 三条合成导师，**无需 Docker、外部数据库或模型密钥**。配置类自身仍默认不启用合成导师，正式数据空态保持独立。

#### 1️⃣ 克隆仓库

```bash
git clone https://github.com/lightporta/Tsing-RADAR.git
cd Tsing-RADAR
```

#### 2️⃣ 启动后端

```bash
cd backend

# 配置环境变量
test -f .env || cp .env.example .env
# 已设置 LLM_ENABLED=false、ALLOW_SIMULATION_MENTORS=true、OBJECT_STORE_BACKEND=local
# 如果已有 .env，请按 .env.example 合并相应项，保留自己的配置。

# 安装依赖（推荐 Python 3.10–3.12；3.14 暂不兼容部分依赖轮子）
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 启动服务
python -m uvicorn app.main:app --reload --port 8000
```

启动后访问：
- 🏠 后端根地址：http://localhost:8000
- 📚 API 交互文档（Swagger）：http://localhost:8000/docs
- ❤️ 健康检查：http://localhost:8000/health

#### 3️⃣ 启动前端

```bash
# 另开终端，从仓库根目录进入前端
cd frontend

# 安装依赖（Node.js 18+）
npm install

# 启动开发服务器
npm run dev
```

#### 4️⃣ 打开应用

🌐 浏览器访问 **http://localhost:5173**

> 💡 **纯前端独立开发**：若只想调试前端，设置 `frontend/.env.development` 中 `VITE_USE_MOCK=true`，无需启动后端。

推荐演示：回答研究方向、研究方式、指导偏好、生涯方向、创新风险和硬约束六轮问题，回复“确认画像”，再查看合成导师的推荐与证据分解。纯前端 Mock 只用于空态和对话展示，不保存服务端画像或生成推荐。

PDF 生成需可嵌入且含中文字形的 TrueType 字体。应用会验证并探测 macOS 的 Arial Unicode / 黑体 / 宋体、Windows 的微软雅黑，以及 Linux 的文泉驿。若系统未安装兼容字体，在 `.env` 设置 `DOCUMENT_CJK_FONT_PATH=/绝对路径/字体.ttf`（或 TrueType `.ttc`）；仅改扩展名不能让 OTF/CFF 字体变得可用。Docker 镜像已安装文泉驿字体。

---

### 🐳 方式二：Docker Compose 本地集成演示

> 拉起 PostgreSQL + Redis + Milvus + 后端 + 前端。根 Compose 使用开发凭据，仅用于本地集成；正式部署请使用 [生产 RUNBOOK](deploy/production/RUNBOOK.md) 和专用生产配置。

#### 1️⃣ 配置环境

```bash
test -f backend/.env || cp backend/.env.example backend/.env
# 示例保持规则模式与合成导师；Compose 覆盖数据库/缓存地址。
```

#### 2️⃣ 一键启动

```bash
docker compose up -d --build
```

#### 3️⃣ 确认迁移完成

```bash
# migration 服务执行 alembic upgrade head，成功退出后才启动后端。
docker compose logs migration backend
# 合成导师与空治理种子均以只读文件挂载，不内置进生产镜像。
```

#### 4️⃣ 打开应用

| 服务 | 地址 |
| :--- | :--- |
| 🌐 **前端应用** | http://localhost |
| 🔧 后端 API | http://localhost:8000 |
| 📚 API 文档 | http://localhost:8000/docs |
| 🗄️ PostgreSQL | localhost:5432 |
| ⚡ Redis | localhost:6379 |
| 📊 Milvus | localhost:19530 |

#### 停止与清理

```bash
docker compose down          # 停止服务（保留数据）
# 删除数据卷属于破坏性操作，不作为常规停止步骤
```

---

### ☁️ 方式三：分别构建镜像（灵活部署）

```bash
# 构建后端镜像
docker build -t tsing-radar-backend ./backend

# 构建前端镜像（内含 nginx，托管静态文件 + 反向代理 API）
docker build -t tsing-radar-frontend ./frontend

# 运行需要显式提供网络、迁移后的数据库和只读导师数据挂载。
# 本地请使用方式二；生产启动顺序和挂载见 deploy/production/RUNBOOK.md。
```

---

## 🔑 环境配置详解

### 后端 `backend/.env`

| 变量 | 必填 | 说明 | 默认值 |
| :--- | :---: | :--- | :--- |
| `LLM_ENABLED` | | 是否允许外部模型配置；本地示例关闭 | 类默认 `true`；示例 `false` |
| `LLM_PROVIDER` | 生产必填 | 生产模型分支：`glm` 或 `deepseek` | 空 |
| `LLM_API_KEY_FILE` | 生产必填 | 只读密钥文件绝对路径 | 空 |
| `GLM_API_KEY` | 仅开发 | 本地开发直连智谱 GLM；生产拒绝 | 空 |
| `DEEPSEEK_API_KEY` | 仅开发 | 本地开发直连 DeepSeek；生产拒绝 | 空 |
| `DATABASE_URL` | | 数据库连接 | `sqlite:///./tsing_radar.db` |
| `REDIS_URL` | | Redis 连接（空则内存缓存） | 空 |
| `MILVUS_HOST` | | 可选向量库地址；当前匹配默认词法/概念召回 | 空 |
| `ADMIN_TOKEN` | | 训练就绪检查管理员 token，未配置不开放 | 空 |
| `ALLOW_SIMULATION_MENTORS` | | 本地 DEBUG 合成导师；生产/非 DEBUG 拒绝 | 类默认 `false`；示例 `true` |
| `OBJECT_STORE_BACKEND` | | 本地私有文件或私有 S3 | `local` |
| `DOCUMENT_CJK_FONT_PATH` | | 可嵌入中文 TrueType 字体绝对路径 | 自动探测系统字体 |
| `CORS_ORIGINS` | | CORS 白名单（逗号分隔） | 本地地址 |

香港生产目标的私有 COS 使用 bucket-free SDK endpoint
`https://cos.ap-hongkong.myqcloud.com`、`S3_REGION=ap-hongkong`、
`S3_ADDRESSING_STYLE=virtual` 与 `S3_SERVER_SIDE_ENCRYPTION=AES256`。
Bucket 必须为 `bucketname-appid` 格式，访问身份仍只通过独立 `*_FILE`
密钥文件注入；应用启动门会拒绝其他区域、path-style、HTTP 或未加密配置。

> ⚠️ 本地开发可使用直接环境变量或确定性 stub。生产环境必须显式配置
> `LLM_PROVIDER=<glm|deepseek>` 与
> `LLM_API_KEY_FILE=/run/secrets/llm_api_key`；密钥值不得进入 Compose 环境、
> Git 或日志。未配置真实模型时只能声明本地规则模式，不能冒充真模型。

### 前端 `frontend/.env.development`

| 变量 | 说明 | 默认值 |
| :--- | :--- | :--- |
| `VITE_API_BASE` | 为空时前端同源；开发代理默认转发至后端 8000 | 空 |
| `VITE_USE_MOCK` | 是否使用前端 Mock 数据（独立开发） | `false` |

### 获取大模型 API Key

| 模型 | 申请地址 | 用途 |
| :--- | :--- | :--- |
| 智谱 GLM | https://open.bigmodel.cn/ | 已编写通用文本/向量适配器，尚未替换主访谈状态机 |
| DeepSeek | https://platform.deepseek.com/ | 已编写通用文本适配器，需后续接入验证 |

本地接开发 Key 时先设置 `LLM_ENABLED=true`。配置 Key 只启用已有适配器，不会自动让访谈、推荐或模板简历变为模型驱动。

---

## 📡 API 接口

完整交互文档启动后端后访问 http://localhost:8000/docs

| 接口 | 方法 | 路径 | 说明 |
| :--- | :--- | :--- | :--- |
| 导师列表 | GET | `/api/mentors` | 分页检索公开资源；显式模拟模式返回合成导师 |
| 旧导师排序 | GET | `/api/mentors/sort?metric=` | 已停用，返回 410 |
| 散点图数据 | GET | `/api/scatter` | 仅有轴证据的公开分布，不含学生匹配分 |
| 综合匹配 | POST | `/api/match` | 读取已确认访谈画像；ranking 控制多目标排序 |
| Web 访谈 | POST | `/api/v1/llm/chat` | 规则状态机 + SSE；路径为兼容保留 |
| 画像编辑/确认 | PATCH/POST | `/api/interviews/{id}/profile`、`.../confirm` | 版本冲突保护与显式确认 |
| 文本向量化 | POST | `/api/v1/llm/embeddings` | GLM embedding / hash 兜底 |
| 招募列表 | GET/POST | `/api/recruitments` | 含急需榜 |
| 简历生成 | POST | `/api/resume/generate` | 确定性生成私有 PDF/DOCX，需确认与幂等键 |
| 简历投递 | POST | `/api/resume/submit` | 仅创建站内记录，不联系第三方 |
| 评价反馈 | POST | `/api/feedback` | 点赞/点踩 + 评论 |
| 训练检查 | POST | `/api/train/trigger` | 管理员数据就绪检查；当前不启动训练 |
| 校内 SSO | GET | `/api/tsinghua/auth/verify` | 清小搭对接占位 |

---

## 🏗 项目结构

```
Tsing-RADAR/
├── frontend/                  # Vue 3 + TypeScript 前端
│   ├── src/
│   │   ├── api/               # Axios 封装 + 各模块 API
│   │   ├── components/        # chat / advisor / charts / common / profile / recruitment
│   │   ├── composables/       # useEChart / useResponsive / useInfiniteScroll / useRadarOption
│   │   ├── layouts/           # PCLayout（三栏）/ MobileLayout / SubPageLayout
│   │   ├── mock/              # 前端独立 Mock（默认诚实空数组）
│   │   ├── router/            # Vue Router（/ /profile /recruitment）
│   │   ├── stores/            # Pinia（chat / advisor / user）
│   │   ├── types/             # TypeScript 类型（无 any）
│   │   ├── utils/             # synergy / markdown / format
│   │   └── views/             # HomeView / ProfileView / RecruitmentView
│   ├── Dockerfile             # 多阶段构建 + nginx
│   └── package.json
│
├── backend/                   # FastAPI 模块化后端
│   ├── app/
│   │   ├── api/v1/            # 10 个路由模块
│   │   ├── core/              # config / deps
│   │   ├── models/            # SQLAlchemy ORM（9 张表）
│   │   ├── schemas/           # Pydantic 请求/响应模型
│   │   ├── services/          # matching / llm / training / vectorstore
│   │   ├── db/                # session / base / redis_client
│   │   ├── graph/             # 预留扩展；当前使用 services/interview.py 状态机
│   │   └── main.py            # FastAPI 入口
│   ├── data/                  # DEBUG 合成导师；正式治理数据由部署只读挂载
│   ├── alembic/               # 数据库迁移
│   ├── scripts/               # init_data / vectorize / crawl
│   ├── tests/                 # pytest；Docker Compose 检查单独标记
│   ├── Dockerfile
│   └── requirements.txt
│
├── legacy/                    # 已弃用旧实现归档；导师能力固定为空状态
├── docker-compose.yml         # 本地基础设施集成演示
├── Tsing-RADAR-项目开发技术文档.md
└── README.md
```

---

## 📐 核心算法

匹配读取服务端已确认画像，依次执行硬约束过滤、可插拔召回和多目标排序。当前默认召回是词法/概念回退，不冒充语义 embedding。

六个排序目标为主题、研究方式、指导方式、生涯、创新与机会。每个目标分别输出适配分、归一化权重和证据置信度，保守总分按各维贡献汇总：

```text
保守总分 = 100 × Σ(目标适配分 × 归一化目标权重 × 该目标证据置信度)
```

无证据维度的贡献为 0，覆盖率与置信度另列。分数表示此配置与现有证据下的排序依据，不是被导师录取的概率。旧六维雷达与多边形重叠工具保留供历史展示，不参与当前匹配；缺少公开象限轴证据的导师不会被补假坐标。

---

## 🧪 测试与质量

```bash
# 后端纯本地业务与合同测试（需系统具备中文PDF字体）
cd backend
python -m pytest -m "not docker" -q

# Docker Compose 配置合同（只验证离线配置，不代表容器或生产验收）
# 未安装 Docker Compose CLI 时明确跳过，可用 -rs 查看原因。
python -m pytest -m docker -q -rs

# 前端另开终端，在仓库根目录执行
cd frontend
npm run type-check
npm run lint
npm run test:state

# 前端生产构建
npm run build
```

---

## 🎨 视觉规范

| 用途 | 颜色 |
| :--- | :--- |
| 主色（清华蓝） | `#409EFF` |
| 辅助色（导师特质） | `#FF9500` |
| 学生需求雷达 | `rgba(64, 158, 255, 0.2)` |
| 导师特质雷达 | `rgba(255, 149, 0, 0.6)` |
| 全局背景 | `#F5F7FA` |

**响应式断点**：≥1200px 三栏 / 1024-1200 压缩 / 768-1024 双栏 / <768px 移动端

---

## 🛠 技术栈

| 层级 | 技术 |
| :--- | :--- |
| **前端** | Vue 3 · TypeScript · Vite · Element Plus · ECharts 5 · Pinia · Vue Router 4 · Axios · SCSS |
| **后端** | FastAPI · SQLAlchemy · Alembic · Pydantic · httpx；LangGraph 为可选扩展 |
| **基础设施** | PostgreSQL · Redis · Milvus · Docker · nginx |
| **大模型** | 智谱 GLM · DeepSeek（生产显式单 provider；本地规则模式仅供开发） |

---

## 🔧 故障排查

<details>
<summary><b>点击展开常见问题</b></summary>

**Q1：启动后端报 `ModuleNotFoundError`？**
→ 确认在 `backend/` 目录下执行了 `pip install -r requirements.txt`，且 Python 版本 ≥ 3.10。

**Q2：前端启动报 `Cannot find module 'xxx'`？**
→ 在 `frontend/` 目录下执行 `npm install`。

**Q3：对话功能返回的是固定模板，不是真 LLM？**
→ 当前运行在本地规则模式（`llm_mode=local_rules`，首页会显示诚实横幅）。本地开发可在 `backend/.env` 配置一个直接
provider Key，并设置 `LLM_ENABLED=true`；这些适配器尚未替换规则访谈主链路。生产部署必须由只读文件提供密钥，并同时设置
`LLM_PROVIDER` 与 `LLM_API_KEY_FILE`。未配置时不能宣称真模型已交付。

**Q3b：导师列表一直是空的？**
→ 配置类默认发布导师为 0（治理空态）；复制当前开发示例则已启用三条合成导师。可在 `DEBUG=true` 下设置 `ALLOW_SIMULATION_MENTORS=true`，加载 `backend/data/mentors.simulation.json`；API/UI 会标明 `simulation_only_not_for_production`，不得当作真实发布数据。

**Q4：前后端跨域报错（CORS）？**
→ 开发期由 vite proxy 自动转发，无需处理。生产期确认 nginx 的 `proxy_pass` 配置正确指向后端。

**Q5：Docker 部署后 Milvus 启动失败？**
→ Milvus 依赖 etcd 与 minio，首次启动较慢，请等待 1-2 分钟。用 `docker compose logs milvus` 查看日志。

**Q6：`alembic upgrade head` 报错？**
→ 确认 `DATABASE_URL` 指向的数据库已启动且凭据正确；psycopg v3 使用 `postgresql+psycopg://`。根 Compose 会先运行 migration 服务，失败时查看 `docker compose logs migration`。SQLite 开发默认自动建表。

**Q7：端口冲突（8000/5173 被占用）？**
→ 后端：`uvicorn ... --port 8001`；前端：修改 `vite.config.ts` 的 `server.port`。

</details>

---

## 📄 文档

- 📋 [项目开发技术文档 v2.1](./Tsing-RADAR-项目开发技术文档.md) — 完整需求规格、数据库设计、API 清单
- 📚 API 交互文档 — 启动后端访问 `/docs`
- 🗄️ 数据库设计 — 技术文档第 5 章（9 张表）
- 📦 旧实现归档 — [`legacy/`](./legacy)（v1 单文件版本，可供对照）

---

## 📝 版本历史

| 版本 | 日期 | 说明 |
| :--- | :--- | :--- |
| v2.2.0 | 2026-10 | 工程质量：本地模拟导师开关、运行态诚实横幅、依赖与文档对齐 |
| v2.1.0 | 2026-07 | 工程化重构：Vue3+TS 前端 + FastAPI 模块化后端 + Docker 部署 |
| v1.0 | 2026-06 | 单文件原型（HTML + FastAPI）|

---

## 📄 许可

清华大学"清小搭"智能体广场内部项目 · 仅供校内师生使用

<div align="center">

**自强不息 · 厚德载物**

Made with ❤️ for Tsinghua students

</div>
