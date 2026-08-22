<div align="center">

# 🛰️ Tsing-RADAR 清研寻师雷达

**Research Advisor Dimension Analysis Radar**

清华大学"清小搭"智能体广场 · 导师智能匹配智能体

从"被动求职"到"主动寻找学术合伙人"

![Version](https://img.shields.io/badge/version-4.2.1-409EFF?style=flat-square)
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
| 🎯 **多维雷达匹配** | 客观四维雷达（证据治理数据）+ 学生需求雷达，多边形重叠面积量化契合度；候选六维对比带 10 格 `█/░` 条形可视化（v3.1.7） |
| 🧮 **契合度构成分解 v3.1.5** | 匹配结果附「契合度构成」：按排序口径倒推各维度贡献，▲拉高/▼拉低/·中位/未计入四类行 + 权重与得分，解释"为什么是 XX 分"（只解释不新增评分，无画像证据的维度诚实标注未计入） |
| 🗣 **对话闭环 v3.1.6** | 匹配后继续追问「第 N 个」→ 候选详情 / 雷达图（按序号签发 SVG）/ 定向套磁邮件，序号越界诚实提示；科研风格速测「确认」回填画像研究方式、方向地图选方向回填研究兴趣（合并去重 + 引导重新确认/招募）——探索结果真正生效，不再"说了但没下文" |
| 🔁 **匹配后二次筛选 v3.1.7** | 匹配后「换一批」（排除已展示候选重跑）/「缩小范围」（两问：聚焦方向 CONTAINS + 排除方向 EXCLUDES）/「恢复完整结果」——过滤态持久化，换批后「第 N 个 / 雷达图 / 套磁」追问与二次筛选批次一致；归零诚实提示绝不编造 |
| 📈 **能力差距分析 v3.1.7** | 每位候选附「能力差距」块：16 规范方向 × 入门知识点（只列公开学科常识，**绝不出现教师名单**），与学生画像兴趣比对输出「已具备 / 建议优先补充 / 学习清单」；无画像证据诚实标注，方向无映射省略 |
| 💬 **LLM 多轮对话** | 高考志愿测评式动态问卷，挖掘学生真实需求画像 |
| ✨ **表达层增强** | LLM 基于确定性事实包整段重写访谈回复；画像确认门与匹配结果不增强，失败完全降级回固定模板 |
| 🔭 **兴趣探索** | 确定性映射（8 研究场景 → 10 方向池，取 top-5 候选），零 LLM 依赖、结果可复现 |
| 📊 **四象限散点图** | 横轴冷热门 × 纵轴国/私，散点大小映射契合度 |
| 🗨️ **纯对话 v2.5** | 清小搭对话内完成：简历从零生成（智能预填+完整性体检）/优化/定向（岗位要求联动）、招募语义筛选（方向同义归一化 NLP↔自然语言处理）与个性化推荐、筛选偏好跨轮记忆、岗位详情追问、宽泛问题引导、四象限与六维对比文本化转译、套磁邮件与 FAQ 咨询（失败全降级确定性、无数据诚实空态）；**仅对话端口无附件能力时雷达图直出文本字符版**（与附件版同一数据来源，客观/主观严格分离） |
| 🧭 **兴趣探索 v3.1.4** | 科研风格速测（4 题确定性分类：范围/推进/形态/成果，9 种核心风格，不判断是否适合科研、不评价能力高低）、研究方向地图（16 公开方向 + 34 别名归一，**只输出方向不输出教师名单**）、画像确认增强（匹配重点 + 未明确项引导） |
| 🧠 **对话意图识别** | 意图优先级分类 + 口语→专业维度映射词典 + 隐式关注识别（连续提及经费/设备自动提示权重），触发词按 51 例真人口语实测扩充（修复 20 处漏匹配），活动模式优先防字段答案劫持；科研风格/方向地图触发词用完整问句结构防访谈误伤 |
| 🧭 **导师评价知识库 v4.0.0** | 综述级词法知识库（任务1 A-1）：姓名精确/子串匹配，只入综述级聚合、**剔除原始引文**、SHA256 可溯源；邮箱/电话/主页/缺点/传闻/研究内容等咨询词路由知识库块，带「公开存档匿名主观评价聚合，仅作参考」声明；未收录诚实拒答，绝不编造联系方式/名额 |
| 🧠 **长期记忆 v4.0.0** | 自有 `user_memories` 表（任务1 A-2，Ultra-Memory 等价物）：只写**已确认画像**白名单事实（未确认猜测绝不写），跨会话召回注入表达层，支持隐私查看/清除 |
| 🛡 **越界话题优雅处理 v4.0.0** | 无关词语（天气/笑话/点外卖）**不再被吞进画像**，温和重问同一题；他人事务（把张三同学的联系方式给我）、篡改指令（把 tolerance 改成 95）、编造请求（编一个名单不用真实数据）一律拦截重问；匹配态跑题给能力引导，空结果不再复读刷屏——直击"问到无关词语就处理不了"痛点 |
| 🔧 **确定性工具注册表 v4.0.0** | 3 只读工具（query_mentor_knowledge / get_recruitments / recall_memory），OpenAI function-calling 对齐 Schema；本期**服务端确定性路由**（LLM 不自主调用，匹配/确认门永不由 LLM 决策），fail-closed 参数校验 |
| 🧪 **离线评估闭环 v4.0.0** | 60 例对抗样本（含红线对抗：诱导编造/篡改数字/他人事务），确定性指标：事实保真逐字、红线违规率 =0；`scripts/eval_offline.py` 一键复跑，报告入 docs |
| 📢 **招募增强 v4.0.0** | FactPack 招募摘要段 + 表达层**逐字校验**（不增强红线）；确认门通过后一次性主动触达（相关开放招募才提示，仅一次不刷屏） |
| 🤖 **双轨雷达对比** | 学生需求（蓝勾边）vs 导师特质（橙勾边），**边缘线图勾连、无颜色填充**（v3.1.5），重叠面积即契合指数 |
| 👨‍🏫 **导师服务门户** | 邮箱验证码登录 / 校园卡核验 / 档案认领与字段级编辑 / 意向中心 / 招募管理 / 隐私控制 |
| ⭐ **导师评分社区** | 六维主观评分（≥8 样本阈值聚合）+ 评论 + 内容审核 |
| 📢 **招募信息平台** | 导师/学长发布招募，含急需榜置顶、评论互动、详情页 |
| 📄 **简历智能管理** | LLM 自动打磨 + 定向导师个性化包装 + 一键投递 |
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
| 动态访谈 | POST | `/api/v1/chat/completions` | OpenAI 协议兼容；含表达层增强 |
| LLM 对话 | POST | `/api/v1/llm/chat` | SSE 流式（问卷追问） |
| 文本向量化 | POST | `/api/v1/llm/embeddings` | GLM embedding / hash 兜底 |
| 兴趣探索 | GET/POST | `/api/interest-exploration/*` | 8 研究场景 → 10 候选方向（确定性映射） |
| 招募列表 | GET/POST | `/api/recruitments` | 含急需榜、详情页 |
| 招募评论 | GET/POST | `/api/recruitments/{id}/comments` | 评论 + 点赞 |
| 导师评分 | GET/POST | `/api/advisors/{id}/ratings` | 五维主观评分，≥8 样本阈值聚合 |
| 简历生成 | POST | `/api/resume/generate` | LLM 打磨 |
| 简历投递 | POST | `/api/resume/submit` | 投递至招募 |
| 评价反馈 | POST | `/api/feedback` | 点赞/点踩 + 评论 |
| 导师登录 | POST | `/api/mentor/auth/*` | 邮箱验证码登录 |
| 校园卡核验 | POST | `/api/mentor/verification/*` | 导师身份核验 |
| 导师档案 | GET/PATCH | `/api/mentor/*` | 认领（`/mentor/claim`）、字段级编辑（进入审批） |
| 导师意向 | GET | `/api/mentor/inbound` | 意向中心（站内投递收件箱） |
| 导师招募 | GET/POST | `/api/mentor/recruitments` | 导师侧招募管理 |
| 导师隐私 | GET/POST | `/api/mentor/privacy/*` | 隐私控制 / 下架申请 |
| 管理审批 | GET/POST | `/api/admin/mentor/*` | 档案编辑与发布审批 |
| 训练触发 | POST | `/api/train/trigger` | 管理员，模型迭代闭环 |
| 校内 SSO | GET | `/api/tsinghua/auth/verify` | 清小搭对接占位 |

---

## 🏗 项目结构

```
Tsing-RADAR/
├── frontend/                  # Vue 3 + TypeScript 前端
│   ├── src/
│   │   ├── api/               # Axios 封装 + 各模块 API
│   │   ├── components/        # chat / advisor / charts / common / mentor / profile / recruitment
│   │   ├── composables/       # useEChart / useResponsive / useInfiniteScroll / useRadarOption
│   │   ├── layouts/           # PCLayout（三栏）/ MobileLayout / SubPageLayout
│   │   ├── router/            # Vue Router（/ /mentors /profile /recruitment /mentor/* /admin/*）
│   │   ├── stores/            # Pinia（chat / advisor / user）
│   │   ├── types/             # TypeScript 类型（无 any）
│   │   ├── utils/             # synergy / markdown / format
│   │   └── views/             # Home / MentorLibrary / Profile / Recruitment(详情) / mentor/* / AdminReview / 404
│   ├── Dockerfile             # 多阶段构建 + nginx
│   └── package.json
│
├── backend/                   # FastAPI 模块化后端
│   ├── app/
│   │   ├── api/v1/            # 26 个路由模块（导师服务 7 个 / 评分 / 评论 / 兴趣探索 / 审批）
│   │   ├── core/              # config / deps / qxd_auth / 安全校验
│   │   ├── models/            # SQLAlchemy ORM（30 张表，含 user_memories / dialogue_sessions / mentor_favorites）
│   │   ├── schemas/           # Pydantic 请求/响应模型
│   │   ├── services/          # matching / llm / interview / chat_expression / mentor_knowledge / memory_service / tools_registry / off_topic / prompts / recruitment_*
│   │   ├── db/                # session / base / redis_client
│   │   └── main.py            # FastAPI 入口
│   ├── data/                  # 运行时只读挂载治理数据；仓库不内置导师记录（data/knowledge 综述级知识库随仓库版本固定，由生产 Compose 只读挂载，不随镜像内置）
│   ├── alembic/               # 数据库迁移（0001-0014 迁移链）
│   ├── scripts/               # init_data / crawl / ingest / audit / export / 治理工具
│   ├── tests/                 # pytest（49 个测试文件，794 用例）
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

### 客观四维雷达（证据治理）

导师客观维度仅展示通过证据治理（来源、授权、字段质量、发布审核）的数据，无证据时不渲染具体数值，只显示"暂无证据"提示。主观评分聚合同理：任一维度样本数 `n < 8` 时不出值（API 层过滤），避免小样本误导。

### 兴趣探索确定性映射

用户多选 8 个研究场景（如"从大量数据里找规律"）后，经静态映射表（方向 → 触发活动键）命中数排序，从 10 方向池中取 top-5 候选。全程零 LLM 调用，结果可复现；选定方向经 apply 写回画像 `research_interests`。

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
# 后端单元 + 集成测试（851 passed / 4 failed（Windows 环境性）/ 2 skipped / 2 errors；
# v4.2.1 新增 19 验收用例：访谈引擎 8 项修复（幽灵硬约束/澄清死循环/回声环/
# SSE 收尾/增强降级/画像清洗/发问去重/无候选兜底，见 docs/访谈引擎修复方案验收记录_v421.md）；
# 离线评估 60 例对抗样本复跑：scripts/eval_offline.py）
python -m pytest backend/tests/ -q

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
| 学生需求雷达勾边 | `#409EFF` |
| 导师特质雷达勾边 | `#FF9500` |
| 全局背景 | `#F5F7FA` |

> v3.1.5 起雷达为**边缘线图勾连**（无颜色填充）：数据系列只描边 + 顶点勾连点，文本版与 PDF 版同风格；网格环仍为浅灰点线。

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

- 📋 [项目开发技术文档 v4.0.0](./Tsing-RADAR-项目开发技术文档.md) — 完整需求规格、数据库设计、API 清单
- 📝 [变更日志 v4.0.0](./CHANGELOG.md) — 全量变更 + 等价物替换理由
- 🐛 [缺陷修复清单 v4.0.0](./docs/缺陷修复清单_v4.md) — 四段式（现象/根因/修复/验证）
- 🔄 [偏差修正记录表 v4.0.0](./docs/偏差修正记录表_v4.md) — 任务书 → 实现等价物替换对照
- 🧪 [评估与提示词优化记录 v4.0.0](./docs/评估与提示词优化记录_v4.md) — 60 例离线评估 + 提示词版本记录 + 工具注册表记录
- 📚 API 交互文档 — 启动后端访问 `/docs`
- 🗄️ 数据库设计 — 技术文档第 5 章
- 🚀 生产部署手册 — [deploy/production/RUNBOOK.md](./deploy/production/RUNBOOK.md)

---

## ⚠️ 已知问题（Windows 开发机环境性，如实记录）

以下 4 failed + 2 errors 与 v3.1.x 基线逐项一致，均为 **Windows 开发机环境性**，
不是 v4.0.0 引入的回归；在 Linux 生产/CI 环境预期通过。不因本机环境差异放宽测试断言。

| 用例 | 原因 |
| :--- | :--- |
| `test_a6_artifacts.py::test_linux_auto_font_prefers_reportlab_compatible_wqy` | 用例按 Linux 路径配置 WQY 字体，Windows 无该字体；生产 Linux 镜像自带字体 |
| `test_l3_handoff.py::test_source_archive_is_byte_deterministic` | 需本地 docker daemon 已构建应用镜像（L3 交接验收口径），本机 docker daemon 未运行 |
| `test_llm_configuration.py::test_missing_and_symlinked_llm_secret_files_fail_closed` + 2 errors | 创建符号链接需管理员/开发者模式特权（`WinError 1314`） |
| `test_llm_configuration.py::test_llm_secret_permissions_reject_group_or_other_access` | Windows 文件系统不强制 POSIX 组/其他权限位 |
| `test_l1_production.py`（整文件收集错误，macOS 开发机） | L1 用例依赖 docker CLI（本地无 docker daemon 时无法收集）；Linux 生产/CI 预期通过，非回归 |

> 完整四段式记录见 [docs/缺陷修复清单_v4.md](./docs/缺陷修复清单_v4.md) 第二节。

---

## 📝 版本历史

| 版本 | 日期 | 说明 |
| :--- | :--- | :--- |
| v4.2.1 | 2026-08 | 访谈引擎修复（压测驱动 8 项）：幽灵硬约束三层消毒、边界澄清死循环闭合、跑题回声环、SSE 收尾必达、单选轮跳过 LLM 增强（零 GLM 等待）、画像字段清洗、流程游走锁定、空结果兜底卡 |
| v4.2.0 | 2026-08 | 表达层多轮自然度增强：FactPack 多轮上下文（最近对话/上一轮实际话术/阶段/风格）+ 跨轮防重复闸门 + 提示词 v3 + get_dialogue_mode 意图劫持修复 |
| v4.1.0 | 2026-08 | 返工批次：雷达文本图 CJK 对齐 + 独立柱状图形态、招募事实句接入生产 FactPack、记忆隐私对话入口（查看/清除）、提示词 v2 自然度 + 机器腔闸门、README .env.example 断链修复 |
| v4.0.0 | 2026-08 | 按《智能体升级执行提示词》全量升级：导师评价综述级词法知识库（A-1）+ 长期记忆 user_memories 表（A-2）+ 提示词版本化（A-3）+ 离线评估闭环 60 例（A-4）+ 确定性工具注册表（阶段B）+ 招募增强（FactPack 逐字校验 + 确认后主动触达）+ 越界话题优雅处理（他人事务/编造/篡改指令拦截、匹配态空态兜底）+ 缺陷修复与文档（详见 CHANGELOG） |
| v3.1.7 | 2026-08 | 匹配后二次筛选闭环（换一批/缩小范围/恢复完整结果）+ 能力差距分析 + 候选官方主页 + 六维 10 格条形 |
| v3.1.6 | 2026-08 | 匹配后「第 N 个」候选追问（详情/雷达/套磁）+ 科研风格速测确认回填 + 方向地图选方向回填画像 |
| v3.1.5 | 2026-08 | 雷达边缘线图勾连（无填充）+ 契合度构成分解 |
| v3.0.0 | 2026-08 | 导师服务门户（登录/认领/意向中心/招募管理/隐私控制）+ 六维评分社区（≥8 样本阈值）+ 兴趣探索确定性映射 + 客观四维雷达 + 访谈表达层增强（LLM 重写、失败降级）+ 迁移链 0012 |
| v2.2.0 | 2026-07 | 审计补丁基线：OpenAI 协议兼容、统一响应封装、鉴权注入、x_soda 附件协议 |
| v2.1.0 | 2026-07 | 工程化重构：Vue3+TS 前端 + FastAPI 模块化后端 + Docker 部署 |
| v1.0 | 2026-06 | 单文件原型（HTML + FastAPI）|

---

## 📄 许可

清华大学"清小搭"智能体广场内部项目 · 仅供校内师生使用

<div align="center">

**自强不息 · 厚德载物**

Made with ❤️ for Tsinghua students

</div>
