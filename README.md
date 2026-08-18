<div align="center">

# 🛰️ Tsing-RADAR 清研寻师雷达

**Research Advisor Dimension Analysis Radar**

清华大学"清小搭"智能体广场 · 导师智能匹配智能体

从"被动求职"到"主动寻找学术合伙人"

![Version](https://img.shields.io/badge/version-2.1.0-409EFF?style=flat-square)
![Vue](https://img.shields.io/badge/Vue-3.5-42b883?style=flat-square)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square)
![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178c6?style=flat-square)
![License](https://img.shields.io/badge/license-Internal-orange?style=flat-square)

</div>

---

## 📖 项目简介

Tsing-RADAR 是一款基于**多维空间向量重合度计算**的导师匹配智能体。通过对话式交互采集学生需求，构建"理想合伙人需求雷达"，与导师"真实特质雷达"做多边形重叠面积量化契合程度，帮助学生克服信息不对称、精准定位最匹配的导师。

### ✨ 核心能力

| 模块 | 说明 |
| :--- | :--- |
| 🎯 **六维雷达匹配** | 学术敏锐度 / 人脉资源 / 指导意愿 / 性格包容度 / 经费实力 / 产出效率 |
| 💬 **LLM 多轮对话** | 高考志愿测评式动态问卷，挖掘学生真实需求画像 |
| 📊 **四象限散点图** | 横轴冷热门 × 纵轴国/私，散点大小映射契合度 |
| 🤖 **双轨雷达对比** | 学生需求（半透明蓝）vs 导师特质（实橙），重叠面积即契合指数 |
| 📄 **简历智能管理** | LLM 自动打磨 + 定向导师个性化包装 + 一键投递 |
| 📢 **招募信息平台** | 导师/学长发布招募，含急需榜置顶 |
| 🔄 **模型迭代闭环** | 反馈 + 问卷样本聚合，梯度下降迭代匹配权重 |

---

## 🖼 界面预览

```
┌─────────────────────────────────────────────────────────────┐
│  🛰️ Tsing-RADAR                    👤 学生信息  💬 信息平台 │  Header 60px
├──────────┬──────────────────────┬──────────────────────────┤
│          │  共找到 N 位匹配导师  │                          │
│  💬 对话  │  [契合度优先 ▾]       │   📊 四象限散点图        │
│  分析区  │──────────────────────│    （默认）              │
│  (35%)   │  ┌──────────────┐   │                          │
│          │  │ 导师卡片+雷达 │   │   点击卡片 → 切换为      │
│  [流式   │  │ ┌────┐ 契合88%│   │   📡 大尺寸双轨雷达图    │
│   追问]  │  │ │雷达│       │   │                          │
│          │  │ └────┘       │   │   契合指数 92%           │
│  [输入框]│  └──────────────┘   │   ✓ 学术敏锐度突出       │
│          │  ┌──────────────┐   │   ✓ 经费充足             │
│          │  │ 导师卡片     │   │                          │
│          │  └──────────────┘   │                          │
└──────────┴──────────────────────┴──────────────────────────┘
```

> 移动端自动切换为：底部对话区（25%）+ 上部卡片与散点（75%）

---

## 🚀 快速开始（部署与打开方案）

提供三种部署方式，按需选择。

### 📦 方式一：本地开发模式（最简，推荐首次体验）

> 前后端分离，开发期默认 SQLite + 内存存储，**无需 Docker、无需数据库**，开箱即用。

#### 1️⃣ 克隆仓库

```bash
git clone https://github.com/lightporta/Tsing-RADAR.git
cd Tsing-RADAR
```

#### 2️⃣ 启动后端

```bash
cd backend

# 配置环境变量
cp .env.example .env
# 本地开发可填 GLM_API_KEY（智谱）
# 生产部署只使用 LLM_PROVIDER + LLM_API_KEY_FILE

# 安装依赖（Python 3.10+）
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
cd frontend

# 安装依赖（Node.js 18+）
npm install

# 启动开发服务器
npm run dev
```

#### 4️⃣ 打开应用

🌐 浏览器访问 **http://localhost:5173**

> 💡 首次本地启动前，先复制 0 记录诚实空态种子（仓库已跟踪）：
> `cp deploy/production/data/empty-mentor-governance.json backend/data/mentors.evidence.json`
> 需要评分链路时同理复制 `empty-mentor-score-governance.json` 并配置 `MENTOR_SCORE_DATA_FILE`。

---

### 🐳 方式二：生产部署（Docker Compose）

> 生产编排全部位于 `deploy/production/`（`compose.infra.yml` + `compose.prod.yml`
> 及边缘/媒体/清小搭网关等追加 compose），完整启动、迁移、密钥与回滚流程见
> [deploy/production/RUNBOOK.md](./deploy/production/RUNBOOK.md)。

```bash
cd deploy/production
cp production.env.example production.env   # 按 RUNBOOK 填入域名与密钥文件路径
docker compose -f compose.infra.yml -f compose.prod.yml up -d
```

数据库迁移由独立一次性任务执行（`compose.jobs.yml`），不随应用容器自动运行。
默认发布导师数据为 0 条；只有通过来源、授权、字段质量和发布审核的治理数据
才能由独立发布流程导入。

---

### ☁️ 方式三：分别构建镜像（灵活部署）

```bash
# 构建后端镜像
docker build -t tsing-radar-backend ./backend

# 构建前端镜像（内含 nginx，托管静态文件 + 反向代理 API）
docker build -t tsing-radar-frontend ./frontend

# 按需运行（自行配置网络与环境变量）
docker run -d -p 8000:8000 --env-file backend/.env tsing-radar-backend
docker run -d -p 80:80 tsing-radar-frontend
```

---

## 🔑 环境配置详解

### 后端 `backend/.env`

| 变量 | 必填 | 说明 | 默认值 |
| :--- | :---: | :--- | :--- |
| `LLM_PROVIDER` | 生产必填 | 生产模型分支：`glm` | 空 |
| `LLM_API_KEY_FILE` | 生产必填 | 只读密钥文件绝对路径 | 空 |
| `GLM_API_KEY` | 仅开发 | 本地开发直连智谱 GLM；生产拒绝 | 空 |
| `DATABASE_URL` | | 数据库连接 | `sqlite:///./tsing_radar.db` |
| `REDIS_URL` | | Redis 连接（空则内存缓存） | 空 |
| `ADMIN_TOKEN` | | 训练触发管理员 token | 空 |
| `CORS_ORIGINS` | | CORS 白名单（逗号分隔） | 本地地址 |

香港生产目标的私有 COS 使用 bucket-free SDK endpoint
`https://cos.ap-hongkong.myqcloud.com`、`S3_REGION=ap-hongkong`、
`S3_ADDRESSING_STYLE=virtual` 与 `S3_SERVER_SIDE_ENCRYPTION=AES256`。
Bucket 必须为 `bucketname-appid` 格式，访问身份仍只通过独立 `*_FILE`
密钥文件注入；应用启动门会拒绝其他区域、path-style、HTTP 或未加密配置。

> ⚠️ 本地开发可使用直接环境变量或确定性 stub。生产环境必须显式配置
> `LLM_PROVIDER=glm` 与
> `LLM_API_KEY_FILE=/run/secrets/llm_api_key`；密钥值不得进入 Compose 环境、
> Git 或日志。未配置真实模型时只能声明本地规则模式，不能冒充真模型。

### 前端 `frontend/.env.development`

| 变量 | 说明 | 默认值 |
| :--- | :--- | :--- |
| `VITE_API_BASE` | 后端 API 地址（vite proxy 转发） | `http://localhost:8000` |

### 获取大模型 API Key

| 模型 | 申请地址 | 用途 |
| :--- | :--- | :--- |
| 智谱 GLM | https://open.bigmodel.cn/ | 对话 / 向量化 / 简历打磨 |

---

## 📡 API 接口

完整交互文档启动后端后访问 http://localhost:8000/docs

| 接口 | 方法 | 路径 | 说明 |
| :--- | :--- | :--- | :--- |
| 导师列表 | GET | `/api/mentors` | 仅返回已通过来源、授权与发布审核的导师；默认 0 条 |
| 导师排序 | GET | `/api/mentors/sort?metric=` | 7 项指标降序 |
| 散点图数据 | GET | `/api/scatter` | 四象限散点 |
| 综合匹配 | POST | `/api/match` | 关键词 + 画像向量 + Synergy |
| LLM 对话 | POST | `/api/v1/llm/chat` | SSE 流式（问卷追问） |
| 文本向量化 | POST | `/api/v1/llm/embeddings` | GLM embedding / hash 兜底 |
| 招募列表 | GET/POST | `/api/recruitments` | 含急需榜 |
| 简历生成 | POST | `/api/resume/generate` | LLM 打磨 |
| 简历投递 | POST | `/api/resume/submit` | 投递至招募 |
| 评价反馈 | POST | `/api/feedback` | 点赞/点踩 + 评论 |
| 训练触发 | POST | `/api/train/trigger` | 管理员，模型迭代闭环 |
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
│   │   ├── router/            # Vue Router（/ /profile /recruitment /mentor/*）
│   │   ├── stores/            # Pinia（chat / advisor / user）
│   │   ├── types/             # TypeScript 类型（无 any）
│   │   ├── utils/             # synergy / markdown / format
│   │   └── views/             # HomeView / ProfileView / RecruitmentView
│   ├── Dockerfile             # 多阶段构建 + nginx
│   └── package.json
│
├── backend/                   # FastAPI 模块化后端
│   ├── app/
│   │   ├── api/v1/            # 25 个路由模块
│   │   ├── core/              # config / deps
│   │   ├── models/            # SQLAlchemy ORM
│   │   ├── schemas/           # Pydantic 请求/响应模型
│   │   ├── services/          # matching / llm / interview / radar_chart / mentor_* / recruitment_*
│   │   ├── db/                # session / base / redis_client
│   │   └── main.py            # FastAPI 入口
│   ├── data/                  # 运行时只读挂载治理数据；仓库不内置导师记录
│   ├── alembic/               # 数据库迁移（0001-0011 迁移链）
│   ├── scripts/               # init_data / crawl / ingest / audit / export / 治理工具
│   ├── tests/                 # pytest
│   ├── Dockerfile
│   └── requirements.txt
│
├── deploy/production/         # 生产编排（compose.*.yml + 边缘网关 + RUNBOOK）
├── scripts/                   # L1/L2/L3 发布与交接校验
├── Tsing-RADAR-项目开发技术文档.md
└── README.md
```

---

## 📐 核心算法

### 合伙人契合指数（Synergy Score）

```
synergy = area(学生需求多边形 ∩ 导师特质多边形) / area(学生需求多边形) × 100%
```

- **六维**：学术敏锐度 / 人脉资源 / 指导意愿 / 性格包容度 / 经费实力 / 产出效率
- **实现**：极坐标 60° 扇区映射 + Shoelace 多边形面积 + per-dim min 近似交集
- **代码**：`backend/app/services/matching.py`（前端镜像 `frontend/src/utils/synergy.ts`）

### 热门指数（Popularity）

```
popularity = 0.4×norm(论文频次) + 0.3×norm(招生帖频次) + 0.3×norm(工业趋势)
```

`> 60` 判定为热门方向，作为散点图横轴。

### 行业性质（Sector）

`0 = 国有机构方向`（航天/军工/国家实验室）/ `1 = 私营企业方向`（互联网/初创），作为散点图纵轴。

---

## 🧪 测试与质量

```bash
# 后端单元 + 集成测试
cd backend && python -m pytest tests/ -v

# 前端类型检查（TypeScript 严格模式，无 any）
cd frontend && npm run type-check

# 前端生产构建
cd frontend && npm run build
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
| **后端** | FastAPI · SQLAlchemy · Alembic · Pydantic · httpx |
| **基础设施** | PostgreSQL · Redis · Docker · nginx · Caddy |
| **大模型** | 智谱 GLM（生产显式单 provider；本地规则模式仅供开发） |

---

## 🔧 故障排查

<details>
<summary><b>点击展开常见问题</b></summary>

**Q1：启动后端报 `ModuleNotFoundError`？**
→ 确认在 `backend/` 目录下执行了 `pip install -r requirements.txt`，且 Python 版本 ≥ 3.10。

**Q2：前端启动报 `Cannot find module 'xxx'`？**
→ 在 `frontend/` 目录下执行 `npm install`。

**Q3：对话功能返回的是固定模板，不是真 LLM？**
→ 当前运行在本地规则模式。本地开发可在 `backend/.env` 配置一个直接
provider Key；生产部署必须由只读文件提供密钥，并同时设置
`LLM_PROVIDER` 与 `LLM_API_KEY_FILE`。未配置时不能宣称真模型已交付。

**Q4：前后端跨域报错（CORS）？**
→ 开发期由 vite proxy 自动转发，无需处理。生产期确认 nginx 的 `proxy_pass` 配置正确指向后端。

**Q5：`alembic upgrade head` 报错？**
→ 确认 `DATABASE_URL` 指向的数据库已启动且凭据正确。SQLite 模式下可直接用 `init_db()` 自动建表。

**Q6：端口冲突（8000/5173 被占用）？**
→ 后端：`uvicorn ... --port 8001`；前端：修改 `vite.config.ts` 的 `server.port`。

</details>

---

## 📄 文档

- 📋 [项目开发技术文档 v2.1](./Tsing-RADAR-项目开发技术文档.md) — 完整需求规格、数据库设计、API 清单
- 📚 API 交互文档 — 启动后端访问 `/docs`
- 🗄️ 数据库设计 — 技术文档第 5 章
- 🚀 生产部署手册 — [deploy/production/RUNBOOK.md](./deploy/production/RUNBOOK.md)

---

## 📝 版本历史

| 版本 | 日期 | 说明 |
| :--- | :--- | :--- |
| v2.1.0 | 2026-07 | 工程化重构：Vue3+TS 前端 + FastAPI 模块化后端 + Docker 部署 |
| v1.0 | 2026-06 | 单文件原型（HTML + FastAPI）|

---

## 📄 许可

清华大学"清小搭"智能体广场内部项目 · 仅供校内师生使用

<div align="center">

**自强不息 · 厚德载物**

Made with ❤️ for Tsinghua students

</div>
