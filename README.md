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

### 📦 本地开发（唯一推荐路径）

> **统一使用 MySQL 8.x**：本地开发与未来生产环境同方言，不再支持 SQLite 运行时。
> SQLite 仅作为历史数据源，由一次性脚本导入到 MySQL，业务运行不走 SQLite 连接。

#### 1️⃣ 克隆仓库

```bash
git clone https://github.com/lightporta/Tsing-RADAR.git
cd Tsing-RADAR
```

#### 2️⃣ 启动本地 MySQL 8.x 并建空库

任选其一（**只需建空数据库 `teacher_db`，不要手动建表，交给 alembic**）：

```bash
# 方案 A：Docker（推荐，跨平台一致）
docker run -d --name tsing-mysql -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=password \
  -e MYSQL_DATABASE=teacher_db \
  mysql:8.0 \
  --character-set-server=utf8mb4 \
  --collation-server=utf8mb4_unicode_ci

# 方案 B：Mac Homebrew
brew install mysql@8
brew services start mysql@8
mysql -uroot -e "CREATE DATABASE teacher_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

#### 3️⃣ 配置后端环境变量

```bash
cd backend
cp .env.example .env
# 编辑 .env，确认/修改 DATABASE_URL（默认指向本地 teacher_db）：
#   DATABASE_URL=mysql+pymysql://root:password@127.0.0.1:3306/teacher_db?charset=utf8mb4
# 大模型必填：GLM_API_KEY=你的智谱 API Key（接真模型用）
```

#### 4️⃣ 安装依赖（Python 3.10+）

```bash
pip install -r requirements.txt
# 已含 PyMySQL + cryptography（MySQL 8 caching_sha2_password 鉴权所需）
```

#### 5️⃣ 执行数据库迁移（建 21 张表）

```bash
python -m alembic upgrade head
# → 创建 9 张 RADAR 规范表 + 2 张私域表 + 10 张业务表 + advisors_public_view 视图
```

#### 6️⃣（可选）导入旧 SQLite 历史数据

如果你之前用 SQLite 存过导师数据，可用一次性脚本迁过来（**业务运行不走 SQLite**）：

```bash
python -m scripts.import_sqlite_data --sqlite-path ./tsing_radar.db
```

#### 7️⃣ 启动后端服务

```bash
python -m uvicorn app.main:app --reload --port 8000
```

启动后访问：
- 🏠 后端根地址：http://localhost:8000
- 📚 API 交互文档（Swagger）：http://localhost:8000/docs
- ❤️ 健康检查：http://localhost:8000/health

#### 8️⃣ 启动前端

```bash
cd ../frontend
npm install           # Node.js 18+
npm run dev
```

#### 9️⃣ 打开应用

🌐 浏览器访问 **http://localhost:5173**

> 💡 **纯前端独立开发**：若只想调试前端，设置 `frontend/.env.development` 中 `VITE_USE_MOCK=true`，无需启动后端。

---

### 🗄️ 数据库迁移命令速查

| 操作 | 命令 |
| :--- | :--- |
| 应用全部迁移到最新 | `python -m alembic upgrade head` |
| 回滚一版 | `python -m alembic downgrade -1` |
| 查看当前版本 | `python -m alembic current` |
| 查看迁移历史 | `python -m alembic history` |
| 离线生成 SQL（不连库） | `python -m alembic upgrade head --sql` |

> 迁移文件全部用 ORM 优先写法，**不含任何 MySQL 专属原生 SQL**。
> 把 `DATABASE_URL` 换成生产实例，`alembic upgrade head` 直接复用。

---

## 🔑 环境配置详解

### 后端 `backend/.env`

| 变量 | 必填 | 说明 | 默认值 |
| :--- | :---: | :--- | :--- |
| `GLM_API_KEY` | ⭐ | 智谱 GLM API Key（接真模型） | 空（降级 stub） |
| `DEEPSEEK_API_KEY` | | DeepSeek API Key（GLM 兜底） | 空 |
| `DATABASE_URL` | ⭐ | MySQL 连接（统一 MySQL 8.x） | `mysql+pymysql://root:password@127.0.0.1:3306/teacher_db?charset=utf8mb4` |
| `REDIS_URL` | | Redis 连接（空则内存缓存） | 空 |
| `MILVUS_HOST` | | Milvus 地址（空则 hash 向量） | 空 |
| `ADMIN_TOKEN` | | 训练触发管理员 token | `admin` |
| `CORS_ORIGINS` | | CORS 白名单（逗号分隔） | 本地地址 |

> ⚠️ **LLM 三级降级策略**：`GLM_API_KEY` → `DEEPSEEK_API_KEY` → 本地 stub。未配置任何 Key 时对话/简历功能降级到本地规则引擎（功能仍可运行，但非真 LLM）。

### 前端 `frontend/.env.development`

| 变量 | 说明 | 默认值 |
| :--- | :--- | :--- |
| `VITE_API_BASE` | 后端 API 地址（vite proxy 转发） | `http://localhost:8000` |
| `VITE_USE_MOCK` | 是否使用前端 Mock 数据（独立开发） | `false` |

### 获取大模型 API Key

| 模型 | 申请地址 | 用途 |
| :--- | :--- | :--- |
| 智谱 GLM | https://open.bigmodel.cn/ | 对话 / 向量化 / 简历打磨（主） |
| DeepSeek | https://platform.deepseek.com/ | GLM 异常时兜底 |

---

## 📡 API 接口

完整交互文档启动后端后访问 http://localhost:8000/docs

| 接口 | 方法 | 路径 | 说明 |
| :--- | :--- | :--- | :--- |
| 导师列表 | GET | `/api/mentors` | 81 位导师（六维雷达 + 热门指数 + 行业性质） |
| 导师排序 | GET | `/api/mentors/sort?metric=` | 7 项指标降序 |
| 散点图数据 | GET | `/api/scatter` | 四象限散点 |
| 综合匹配 | POST | `/api/match` | 关键词 + 画像向量 + Synergy |
| LLM 对话 | POST | `/api/v1/llm/chat` | SSE 流式（问卷追问） |
| 文本向量化 | POST | `/api/v1/llm/embeddings` | GLM embedding / hash 兜底 |
| 招募列表 | GET/POST | `/api/recruitments` | 含急需榜 |
| 简历生成 | POST | `/api/resume/generate` | LLM 打磨（附件受 PUBLIC_BASE_URL 门禁） |
| 简历投递 | POST | `/api/resume/submit` | 投递至招募 |
| 对象上传 | POST | `/api/storage/upload` | 私有文件（PDF/DOCX），builtin 扫描，失败关闭 |
| 对象下载 | GET | `/api/storage/download` | 一次性签名令牌 + Cache-Control: no-store |
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
│   │   ├── mock/              # 前端独立 Mock（81 位导师）
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
│   │   ├── api/v1/            # 路由模块（含 v2 导师接口 + storage）
│   │   ├── core/              # config / deps / response
│   │   ├── models/            # SQLAlchemy ORM（21 张表：业务 10 + RADAR 公开层 9 + 私域层 2）
│   │   ├── schemas/           # Pydantic 请求/响应模型
│   │   ├── services/          # matching / llm / training / security / storage / scanner / signing
│   │   ├── db/                # session / base / redis_client
│   │   ├── graph/             # 对话编排（占位）
│   │   └── main.py            # FastAPI 入口
│   ├── scripts/               # build_database / crawl_live / init_data / import_sqlite_data / vectorize_advisors
│   ├── alembic/               # 数据库迁移（0001 ~ 0004，跨方言兼容）
│   ├── scripts/               # init_data / vectorize / crawl
│   ├── tests/                 # pytest（23 项测试）
│   ├── Dockerfile
│   └── requirements.txt
│
├── docker-compose.yml         # 完整基础设施编排
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
# 后端单元 + 集成测试（v2.2：71 项，含安全原语与对象存储）
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
| **后端** | FastAPI · SQLAlchemy · Alembic · Pydantic · httpx · LangGraph |
| **基础设施** | MySQL 8.x · Redis（可选） · Milvus（可选） · Docker · nginx |
| **大模型** | 智谱 GLM · DeepSeek（三级降级） |

---

## 🔧 故障排查

<details>
<summary><b>点击展开常见问题</b></summary>

**Q1：启动后端报 `ModuleNotFoundError`？**
→ 确认在 `backend/` 目录下执行了 `pip install -r requirements.txt`，且 Python 版本 ≥ 3.10。

**Q2：前端启动报 `Cannot find module 'xxx'`？**
→ 在 `frontend/` 目录下执行 `npm install`。

**Q3：对话功能返回的是固定模板，不是真 LLM？**
→ 未配置 `GLM_API_KEY` / `DEEPSEEK_API_KEY`，已降级到本地 stub。在 `backend/.env` 填入 Key 后重启。

**Q4：前后端跨域报错（CORS）？**
→ 开发期由 vite proxy 自动转发，无需处理。生产期确认 nginx 的 `proxy_pass` 配置正确指向后端。

**Q5：Docker 部署后 Milvus 启动失败？**
→ Milvus 依赖 etcd 与 minio，首次启动较慢，请等待 1-2 分钟。用 `docker-compose logs milvus` 查看日志。

**Q6：`alembic upgrade head` 报错？**
→ 确认 `DATABASE_URL` 指向的 MySQL 8.x 已启动、`teacher_db` 数据库已创建、账号有 DDL 权限。
→ 查看错误堆栈，常见为密码错误（caching_sha2_password 鉴权需 cryptography 库）或字符集非 utf8mb4 导致中文乱码。

**Q7：端口冲突（8000/5173 被占用）？**
→ 后端：`uvicorn ... --port 8001`；前端：修改 `vite.config.ts` 的 `server.port`。

</details>

---

## 📄 文档

- 📋 [项目开发技术文档 v2.1](./Tsing-RADAR-项目开发技术文档.md) — 完整需求规格、数据库设计、API 清单
- 📊 [当前开发状态与未关闭门禁](./docs/前两版基础上的改动与当前开发状态总结.md) — v2.2 真实能力与 10 项待授权门禁
- 📚 API 交互文档 — 启动后端访问 `/docs`
- 🗄️ 数据库设计 — 技术文档第 5 章 + v2.2 新增 `storage_objects` 表

---

## 📝 版本历史

| 版本 | 日期 | 说明 |
| :--- | :--- | :--- |
| v2.2.0 | 2026-07 | 离线安全加固：删除 legacy、SSRF/有界读取/日志脱敏原语、对象存储与扫描适配器骨架、签名下载令牌、附件协议公网基址门禁、文档校正为与代码一致 |
| v2.1.0 | 2026-07 | 工程化重构：Vue3+TS 前端 + FastAPI 模块化后端 + Docker 部署 |
| v1.0 | 2026-06 | 单文件原型（HTML + FastAPI，已在 v2.2 删除）|

---

## 📄 许可

清华大学"清小搭"智能体广场内部项目 · 仅供校内师生使用

<div align="center">

**自强不息 · 厚德载物**

Made with ❤️ for Tsinghua students

</div>
