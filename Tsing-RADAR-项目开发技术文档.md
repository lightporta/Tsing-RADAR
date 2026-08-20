# Tsing-RADAR 项目开发技术文档
## Research Advisor Dimension Analysis Radar / 清研寻师雷达

> 部署平台：清华大学"清小搭"智能体广场
> 文档版本：v4.0.0
> 更新日期：2026年8月

---

## 目录

1. 项目概述
2. 需求规格说明
3. 核心匹配机制：学术合伙人雷达图
4. 系统架构与 UI/UX 设计
5. 数据库设计
6. API 接口文档
7. 测试计划
8. 部署与运维
9. 模型训练与迭代闭环
10. v3.0 导师服务与表达层增强
11. v3.1 纯对话升级（v2.5 规格）
12. v4.0.0 智能体升级（任务书四任务全量交付）

---

## 1. 项目概述 (Project Overview)

### 1.1 项目背景

在清华大学，学生在选择导师时普遍面临"信息不对称"困境。全校导师众多、研究方向广泛，低年级本科生和新生难以全面了解导师的学术背景、指导风格及招生要求，更缺乏将个人兴趣与导师方向有效匹配的能力。

目前，"清小搭"平台已具备智能问答、成长评测等基础功能，并推出了"学业志趣自测"，但现有的导师推荐多停留在"信息展示"层面，缺乏深度的个性化匹配。同类项目（如北航面向"三早"培养的"知遇"平台、开源项目 `advisor-finder`）已证明智能体匹配的可行性。

### 1.2 项目目标

- **降本增效**：帮助学生在海量信息中快速定位最匹配的导师，降低检索成本。
- **认知升级**：依托 AI 个性化匹配，帮助学生探索自我，将"被动求职"转变为"主动寻找学术合伙人"。
- **生态补充**：作为"清小搭"智能体广场的新成员，深化现有导师推荐功能，实现学业初期兴趣与科研方向的精准对接。

### 1.3 项目范围

开发名为 **Tsing-RADAR (Research Advisor Dimension Analysis Radar / 清研寻师雷达)** 的智能体，覆盖需求采集、多源数据抓取、大模型契合度分析、可视化展示、多轮交互追问、简历管理、招募对接全流程，部署于清华大学"清小搭"智能体广场，服务全校师生。

---

## 2. 需求规格说明 (Requirement Specification)

### 2.1 功能需求 (Functional Requirements)

#### 2.1.1 多模态需求采集

- 支持对话式交互，采集学生专业背景、研究兴趣、职业规划等核心信息。
- 支持对接"清小搭"现有"学业志趣自测"API，复用历史评测数据。
- 支持上传 PDF/Word 格式的简历、个人陈述（PS），通过大模型提取科研经历与兴趣标签。

#### 2.1.2 导师数据自动化构建

- **批量抓取**：输入院系师资页面 URL，自动抓取导师研究方向、学术背景、教学经历。
- **定向深挖**：指定某位导师，自动聚合其联系方式、个人主页、近两年发表的论文（对接图书馆数据库）。
- **知识库维护**：构建结构化导师向量知识库（Vector DB），支持定期增量更新。

#### 2.1.3 智能匹配与多维排序

- 基于大模型分析学生兴趣与导师方向的契合度，输出推荐列表、契合度评分及个性化推荐理由。
- 支持按7项核心指标对导师列表进行降序重排，满足不同偏好的筛选需求。

#### 2.1.4 LLM 交互式动态问卷

- 由大模型驱动动态问卷，通过多轮深度追问挖掘学生兴趣偏好与核心需求。
- 根据用户上一轮回答动态生成下一轮问题，最终产出精准用户画像作为匹配输入。
- 保留关键词输入作为快捷兜底入口。

#### 2.1.5 多轮交互与 RAG 追问

- 支持基于检索增强生成（RAG）的多轮对话，可追问导师研究进展、组内管理风格、招生要求等细节问题。
- 回答严格基于知识库检索结果，避免信息编造。
- **v4.0.0 实现**：以**综述级词法知识库**作为确定性等价物（见 §12.1）——语料只入综述级聚合、
  剔除原始引文、SHA256 可溯源；姓名精确/子串匹配零幻觉；未收录诚实拒答。无 chroma/langchain
  依赖、无 key 可跑。

#### 2.1.6 简历智能生成与管理

- 内嵌简历智能助手，支持自动补全学生基础信息，录入项目经历、奖项、学生工作等内容。
- 调用大模型自动生成、优化打磨简历，支持定向导师个性化包装。
- 提供简历查看、编辑、删除、下载全生命周期管理。

#### 2.1.7 招募信息平台

- 支持导师、学长学姐发布实习、科研助理、招生类招募信息。
- 设急需榜，对紧急招募进行置顶展示。
- 学生可通过入口直接投递简历至对应招募，流程闭环。

#### 2.1.8 结果导出

- 支持将推荐报告（含雷达图、匹配得分、推荐理由）导出为 Markdown 或 PDF 文件。

#### 2.1.9 用户反馈机制

- 导师卡片开放点赞/点踩评价与评论输入。
- 反馈数据统一入库，用于模型迭代与效果优化。

#### 2.1.10 导师服务门户（v3.0）

- 导师以清华邮箱接收验证码登录，支持校园卡身份核验。
- 导师认领治理档案后可对个人主页字段（研究方向、联系方式等）发起字段级编辑，进入管理员审批队列。
- 意向中心：导师查看学生站内投递意向，管理已读/拒绝状态。
- 招募管理：导师发布、编辑、下架自己的招募信息。
- 隐私控制：导师可申请隐藏联系方式或申请档案下架（takedown）。

#### 2.1.11 导师评分社区（v3.0）

- 学生对导师六维特质（学术敏锐度/人脉资源/指导意愿/性格包容度/经费实力/产出效率）提交主观评分。
- 聚合展示设 ≥8 样本阈值：任一维度样本数不足时不出值，避免小样本误导。
- 招募详情页支持评论、点赞与举报，内容经审核后展示。

#### 2.1.12 兴趣探索（v3.0）

- 面向研究方向不明确的学生：从 8 个研究场景（"想做什么样的活动"）多选入手。
- 经静态映射表确定性推导候选研究方向（10 方向池，取 top-5），零 LLM 依赖、结果可复现。
- 选定方向写回画像 `research_interests`，进入后续匹配链路。

#### 2.1.13 访谈回复表达层增强（v3.0）

- LLM 基于确定性事实包（访谈状态投影）整段自然重写访谈回复，提升对话体验。
- 诚实性红线：画像确认门（needs_confirmation）与匹配结果（recommend_ready）不增强，保持确定性原文。
- 平台探测请求跳过；无凭据或任何失败（超时/校验不过）完全降级回固定模板，fail-closed。

### 2.2 非功能需求 (Non-Functional Requirements)

| 类别 | 需求项 | 指标 |
| :--- | :--- | :--- |
| 隐私与安全 | 数据保密 | 严格遵守清华大学数据保密规定，学生敏感信息加密，导师未公开信息脱敏或权限控制 |
| 响应性能 | 对话首字响应 | < 1.5s |
| 响应性能 | 雷达图生成与渲染 | < 2s |
| 高可用性 | LLM 超时与降级 | GLM 服务异常时按超时预算降级为本地规则模式，不伪造模型输出 |
| 并发支持 | 并发用户数 | ≥ 500 并发用户 |
| 可用率 | 系统可用率 | ≥ 99.5% |

---

## 3. 核心匹配机制：学术合伙人雷达图 (Core Matching Mechanism)

本系统核心壁垒在于将传统"文本相似度匹配"升级为**多维空间向量重合度计算**，为学生构建"理想合伙人需求雷达"，为导师生成"真实特质雷达"，通过多边形重叠面积量化契合程度。

### 3.1 六边形维度定义

雷达图共包含 6 个核心维度，单维度分值范围 0-100 分：

| 维度名称 | 英文标识 | 维度含义 |
| :--- | :--- | :--- |
| 学术敏锐度 | Acumen | 前沿课题捕捉能力、顶会/顶刊发表能力 |
| 人脉资源 | Network | 学术界人脉、工业界合作资源、推荐出国/就业能力 |
| 指导意愿 | Mentorship | 手把手指导频率、组会交流深度、对学生心理的关注度 |
| 性格包容度 | Tolerance | 对失败的包容度、管理风格（微操型 vs 放养型）、情绪稳定性 |
| 经费实力 | Funding | 课题组算力/实验设备充裕度、助研津贴发放水平 |
| 产出效率 | Efficiency | 论文审稿周期、学生平均毕业年限、延毕率 |

### 3.2 合伙人契合指数 (Synergy Score)

#### 3.2.1 动态权重分配

学生可根据自身短板调整各维度权重，所有权重之和归一化为 100%。例如：学生创意多但算力不足，可调高"经费实力"权重至 30%。

#### 3.2.2 核心计算公式

将学生需求向量 S 与导师特质向量 A 映射至六边形极坐标系，通过多边形交集面积计算契合程度：

```
合伙人契合指数 (Synergy Score) = 学生需求多边形 ∩ 导师特质多边形面积 / 学生需求多边形面积 × 100%
```

输出结果范围为 0-100，数值越高代表匹配度越高。

### 3.3 热门指数计算 (Popularity Index)

用于衡量导师研究方向的热门程度，分值范围 0-100，计算公式：

```
popularity = 0.4 × norm(领域关键词近1年论文频次) + 0.3 × norm(领域近1年招生帖频次) + 0.3 × norm(领域工业趋势热度)
```

**阈值规则**：

- `popularity > 60` 判定为「热门方向」
- `popularity ≤ 60` 判定为「冷门方向」

该指标作为二维散点图横轴，同时纳入导师列表排序指标体系。

### 3.4 行业性质判定 (Sector Classification)

用于二维散点图纵轴，将导师研究方向按产业属性分为两类：

- **「国」（国有机构方向）**：航天、军工、国家实验室、院所事业单位等体制内方向
- **「私」（私营企业方向）**：互联网大厂、初创公司、商业化产业等市场化方向

判定依据为导师近年论文关键词、专利/项目来源、合作企业性质，由大模型分类生成 `sector` 字段，取值 0-1（0=纯国有，1=纯私营）。

### 3.5 重叠面积精算逻辑

#### 3.5.1 坐标系映射

将六维雷达映射至极坐标系，每个维度对应 60° 扇区，维度分值对应极径长度。

#### 3.5.2 算法实现

- 采用 **Shoelace 公式** 计算单个多边形面积
- 采用 **Sutherland-Hodgman 多边形裁剪算法** 求解两个多边形的交集面积

#### 3.5.3 归一化规则

分母固定为学生需求多边形面积，确保结果始终落在 [0, 100%] 区间，支持跨学生横向比较。

---

## 4. 系统架构与 UI/UX 设计 (System Architecture & UI Design)

### 4.1 整体技术架构

采用前后端分离的分层架构，整体分为表现层、业务逻辑层、数据访问层、外部接口层四层：

| 架构层级 | 技术选型 | 说明 |
| :--- | :--- | :--- |
| 前端表现层 | Vue 3 + TypeScript + ECharts | 响应式卡片列表、雷达图/散点图可视化 |
| 业务逻辑层 | Python / FastAPI | 异步高性能 API 服务 |
| 大模型层 | 智谱 GLM 系列 | 语义分析、匹配推理、自然语言生成（单 provider，文件型密钥） |
| 关系数据库 | PostgreSQL | 学生、导师、业务流程结构化数据存储 |
| 缓存层 | Redis | 对话上下文缓存、推荐结果缓存 |
| 数据采集层 | Scrapy + Playwright | 师资页面抓取、个人主页信息采集 |
| 邮件服务 | 清华邮箱 SMTP | 通过 OAuth 2.0 授权发送邮件 |

### 4.2 双端自适应布局

采用响应式设计，适配 PC 端与移动端，核心断点与布局策略如下：

| 设备类型 | 宽度区间 | 布局策略 |
| :--- | :--- | :--- |
| PC 端 | ≥1024px | 三栏布局：左对话 + 中卡片列表 + 右散点图/雷达图 |
| 平板 | 768–1024px | 双栏自适应，对话栏可折叠收起 |
| 大屏手机 | 480–768px | 单栏上下堆叠，底部固定对话输入区 |
| 小屏手机 | <480px | 精简核心功能，对话区固定底部占 1/4 屏幕 |

#### 4.2.1 PC 端三栏布局

整体采用左-中-右三栏结构，顶部为全局 Header 导航栏：

**Header 导航栏**
- 左上角：智能体 Logo 与名称
- 右上角：学生信息按钮（人形图标）、「信息平台」按钮
- 取消全局「退出/重置」按钮，对话重置功能收归至对话栏内部

**左栏（对话分析区，约占屏幕宽度 35%）**
- 顶部工具栏：
  - 左侧：「收起」按钮（点击后对话栏向左折叠收起，再次点击展开恢复）
  - 右侧：「新对话+」按钮（清空当前会话上下文，开启全新对话）
- 主体区域：聊天气泡式对话界面，AI 回复居左、用户消息居右，支持流式输出
- 底部：消息输入框 + 发送按钮 + 附件上传入口
- 对话内容驱动导师匹配，实时更新中部与右侧展示内容

**中栏（导师卡片列表区，约占屏幕宽度 35%）**
- 顶部：匹配结果数量统计与排序筛选下拉菜单
- 主体：导师卡片纵向罗列，数据接入学校导师数据库后动态渲染
- 每张卡片内嵌迷你双轨雷达图（学生需求 vs 导师特质）
- 支持滚动加载更多，卡片点击后联动右侧区域切换展示

**右栏（可视化看板区，约占屏幕宽度 30%）**
- **默认状态**：展示二维四象限散点图
  - 横轴：热门指数（左冷 / 右热）
  - 纵轴：行业性质（上国 / 下私）
  - 四个象限：国热、国冷、私热、私冷
  - 每个散点对应一位导师，悬浮显示姓名与契合度
- **点击导师卡片后**：散点图切换为该导师的**完整大尺寸雷达图**
  - 六维度双轨对比（学生需求蓝色勾边 + 导师特质橙色勾边，v3.1.5 起为边缘线图勾连、无颜色填充）
  - 下方展示契合指数得分与核心匹配理由
  - 保留返回散点图的切换按钮

#### 4.2.2 移动端布局

采用上下堆叠结构，对话区固定底部，类原生 AI App 交互：

**底部对话区（固定占屏幕高度 1/4）**
- 顶部对话栏标题 + 「新对话+」按钮 + 展开/收起切换
- 对话消息可上下滚动查看
- 底部输入框常驻，支持语音输入快捷入口

**上部内容区（占屏幕高度 3/4，可上下滑动）**
- 第一区块：导师推荐卡片列表，纵向排列，每张卡片含迷你雷达图
- 第二区块：二维四象限散点图，点击可放大全屏查看
- 顶部导航栏收纳学生信息、信息平台入口至汉堡菜单

### 4.2.3 二级页面导航规范

学生信息页面、信息平台页面均为**独立全屏二级页面**，与主界面尺寸一致，非抽屉式或通知栏式小界面：

- 页面左上角统一设置「← 返回」按钮，点击回退至智能体首页主界面
- 页面顶部保留与首页一致的 Header 高度与视觉风格
- 页面内内容独立滚动，不影响主界面会话状态
- 支持浏览器前进/后退历史记录栈管理

### 4.3 核心交互组件设计

#### 4.3.1 导师卡片 (Advisor Card)

- 外观为横向圆角长方形卡片，左侧展示导师头像、姓名、院系与职称
- 中部排列 3-4 个核心研究方向关键词标签，下方显示契合度百分比
- 右侧内嵌**迷你双轨雷达图**：蓝色勾边代表学生需求轮廓，橙色勾边代表导师特质（v3.1.5 起边缘线图勾连、无颜色填充），重叠区域高亮
- 卡片点击为选中态，高亮边框，同时触发右侧看板切换为该导师的完整大雷达图
- 卡片支持二次点击展开详情面板，向下滑出近期论文、学生评价、在研项目、招募信息

#### 4.3.2 二维四象限散点图看板

- 横轴：热门指数（左侧冷方向 → 右侧热方向）
- 纵轴：行业性质（上方国有方向 → 下方私营方向）
- 平面划分为四个象限：国热（左上）、国冷（左下）、私热（右上）、私冷（右下）
- 每个散点对应一位导师，散点大小映射契合度得分，颜色区分院系
- 悬浮散点显示导师姓名与契合度，点击散点联动选中中部对应导师卡片
- 提供象限筛选按钮，可快速只展示某一象限内的导师

#### 4.3.3 导师详情大雷达图

- 仅在选中具体导师时展示于右栏看板区域，替代默认散点图
- 完整六维度双轨雷达图，大尺寸清晰展示每一维度的对比差距
- 雷达图下方展示合伙人契合指数总分、维度逐项对比说明、大模型生成的匹配理由
- 底部设「返回散点图」按钮，切回全局四象限概览

#### 4.3.4 一键联系功能

- 导师详情面板内置醒目的「联系导师」按钮
- 系统校验当前登录学生身份，点击后自动唤起邮件客户端或调用内部邮件网关
- 自动填充收件人（导师官方邮箱）、邮件主题、附带学生简历附件
- 默认主题格式：`【Tsing-RADAR 推荐】关于攻读您研究生的咨询 - [学生姓名]`

### 4.4 全局控制与导航

- **对话栏收起按钮**：位于对话栏左上角，点击后对话栏向左折叠收起，腾出更多空间展示导师卡片与散点图；收起状态下再次点击展开恢复
- **新对话+ 按钮**：位于对话栏右上角，点击清空当前会话上下文，开启全新对话，不影响已加载的导师数据
- **学生信息入口**：顶部 Header 人形图标按钮，点击进入独立全屏的个人信息与简历管理页面，左上角设返回按钮
- **信息平台入口**：顶部 Header「信息平台」按钮，点击进入独立全屏的招募信息列表页面（含急需榜），左上角设返回按钮
- 取消全局「退出/重置」按钮，所有会话重置操作均通过对话栏内的「新对话+」完成

---

## 5. 数据库设计 (Database Design)

采用关系型数据库（PostgreSQL；本地开发默认 SQLite）存储结构化业务数据，匹配主链路为确定性词法召回与六维雷达多边形重合度计算。

### 5.1 核心基础数据表

#### 表 1：students（学生信息表）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| student_id | VARCHAR(20) | 主键，清华学号 |
| email | VARCHAR(50) | 学生清华邮箱，用于身份校验和发邮件 |
| department | VARCHAR(50) | 所在院系 |
| gender | TINYINT | 性别 |
| category | VARCHAR(20) | 类别：本科生/硕士生/博士生 |
| phone | VARCHAR(20) | 联系电话，加密存储 |
| interest_vector | JSON/VECTOR | 学业志趣自测结果及雷达图权重配置 |

#### 表 2：advisors（导师画像表）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| advisor_id | VARCHAR(20) | 主键，教职工工号 |
| name | VARCHAR(50) | 导师姓名 |
| department | VARCHAR(50) | 所在系别 |
| profile_text | TEXT | 个人简介，来自百科/主页抓取 |
| recent_papers | JSON | 近两年论文列表，对接图书馆数据库 |
| contact_email | VARCHAR(50) | 导师官方邮箱 |
| office_loc | VARCHAR(50) | 办公室地址，例：FIT楼 3-112 |
| radar_traits | JSON | 六边形雷达图得分，由大模型评估生成 |
| popularity | FLOAT | 研究方向热门指数，0-100 |
| sector | FLOAT | 行业性质分值，0=纯国有，1=纯私营 |

#### 表 3：match_records（匹配历史表）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| record_id | UUID | 主键 |
| student_id | VARCHAR(20) | 外键，关联学生学号 |
| advisor_id | VARCHAR(20) | 外键，关联导师工号 |
| synergy_score | FLOAT | 合伙人契合指数，0-100 |
| match_reason | TEXT | 大模型生成的个性化推荐理由 |
| created_at | TIMESTAMP | 匹配时间 |

### 5.2 v2 新增业务数据表

#### 表 4：resumes（简历表）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| resume_id | UUID | 主键 |
| student_id | VARCHAR(20) | 外键，关联学生学号 |
| title | VARCHAR(100) | 简历标题 |
| content | JSON | 结构化简历内容 |
| polished_text | TEXT | 大模型打磨后的简历正文 |
| target_advisor_id | VARCHAR(20) | 定向适配导师ID |
| created_at | TIMESTAMP | 创建时间 |

#### 表 5：recruitments（招募表）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| recruit_id | UUID | 主键 |
| publisher_id | VARCHAR(20) | 发布者ID |
| publisher_type | VARCHAR(20) | 发布者类型：advisor/senior |
| type | VARCHAR(20) | 招募类型：实习/科研助理/招生 |
| title | VARCHAR(200) | 招募标题 |
| req | TEXT | 招募要求 |
| major | VARCHAR(100) | 所属专业板块 |
| deadline | DATE | 截止日期 |
| is_urgent | BOOLEAN | 是否急招 |
| created_at | TIMESTAMP | 发布时间 |

#### 表 6：applications（投递表）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| app_id | UUID | 主键 |
| recruit_id | UUID | 外键，关联招募ID |
| student_id | VARCHAR(20) | 外键，关联学生学号 |
| resume_id | UUID | 外键，关联投递简历ID |
| status | VARCHAR(20) | 投递状态：待处理/已读/通过/拒绝 |
| created_at | TIMESTAMP | 投递时间 |

#### 表 7：feedback（反馈表）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| feedback_id | UUID | 主键 |
| student_id | VARCHAR(20) | 外键，关联学生学号 |
| advisor_id | VARCHAR(20) | 外键，关联导师工号 |
| rating | TINYINT | 评价：1=赞，-1=踩 |
| comment | TEXT | 评论内容 |
| created_at | TIMESTAMP | 反馈时间 |

#### 表 8：questionnaire_sessions（问卷会话表）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| session_id | UUID | 主键 |
| student_id | VARCHAR(20) | 外键，关联学生学号 |
| messages | JSON | 多轮对话历史 |
| portrait | JSON | 生成的用户画像 |
| created_at | TIMESTAMP | 创建时间 |

#### 表 9：training_samples（训练样本表）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| sample_id | UUID | 主键 |
| student_id | VARCHAR(20) | 外键，关联学生学号 |
| questionnaire_id | UUID | 外键，关联问卷会话ID |
| chosen_advisor_id | VARCHAR(20) | 最终选组导师ID |
| features | JSON | 匹配特征向量 |
| label | FLOAT | 契合度标签 |
| created_at | TIMESTAMP | 创建时间 |

### 5.3 v3.0 新增业务数据表

#### 表 10：mentor_accounts（导师账户表）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| mentor_id | UUID | 主键 |
| email | VARCHAR(100) | 唯一，清华邮箱（仅机构邮箱） |
| display_name | VARCHAR(50) | 姓名 |
| status | VARCHAR(20) | 账户状态 |
| created_at | TIMESTAMP | 注册时间 |

#### 表 11：mentor_claims（导师档案认领表）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| claim_id | UUID | 主键 |
| mentor_id | UUID | 外键，导师账户 |
| advisor_id | VARCHAR(20) | 外键，治理档案导师 ID |
| status | VARCHAR(20) | 认领状态（pending/approved/rejected） |
| evidence | JSON | 认领证据 |
| created_at | TIMESTAMP | 申请时间 |

#### 表 12：mentor_profiles（导师公开档案表）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| advisor_id | VARCHAR(20) | 主键，治理档案导师 ID |
| verified_profile | JSON | 已验证字段（含研究方向、联系方式） |
| publication_status | VARCHAR(20) | restricted / published |
| updated_at | TIMESTAMP | 最后更新时间 |

#### 表 13：mentor_profile_edits（导师档案编辑审批表）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| edit_id | UUID | 主键 |
| mentor_id | UUID | 外键，发起编辑的导师 |
| field_name | VARCHAR(50) | 编辑字段名 |
| new_value | TEXT | 新值（diff 存档） |
| review_status | VARCHAR(20) | pending_review / approved / rejected |
| reviewed_by | VARCHAR(50) | 审批管理员 |
| created_at | TIMESTAMP | 提交时间 |

#### 表 14：mentor_campus_cards（导师校园卡核验表）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| verification_id | UUID | 主键 |
| mentor_id | UUID | 外键，导师账户 |
| card_last4 | VARCHAR(8) | 校园卡号后 4 位（脱敏） |
| verification_status | VARCHAR(20) | 核验状态 |
| verified_at | TIMESTAMP | 核验时间 |

#### 表 15：advisor_ratings（导师评分表）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| rating_id | UUID | 主键 |
| advisor_id | VARCHAR(20) | 外键，导师 ID |
| student_id | VARCHAR(20) | 外键，学生学号 |
| acumen…efficiency | SMALLINT | 六维评分（0-10） |
| created_at | TIMESTAMP | 评分时间 |

#### 表 16：advisor_rating_summary（导师评分聚合表）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| advisor_id | VARCHAR(20) | 主键 |
| {dim}_value / {dim}_n | FLOAT / INT | 各维度聚合值与样本数（服务层保留原始聚合，API 层过滤 n<8） |
| last_collected_at | TIMESTAMP | 最后收集时间 |

#### 表 17：recruitment_comments（招募评论表）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| comment_id | UUID | 主键 |
| recruit_id | UUID | 外键，招募 ID |
| student_id | VARCHAR(20) | 评论学生 |
| content | TEXT | 评论内容（经内容审核） |
| moderation_status | VARCHAR(20) | 审核状态 |
| created_at | TIMESTAMP | 评论时间 |

#### 表 18：takedown_requests（档案下架申请表）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| request_id | UUID | 主键 |
| mentor_id | UUID | 外键，发起导师 |
| advisor_id | VARCHAR(20) | 目标档案 |
| reason | TEXT | 下架理由 |
| status | VARCHAR(20) | 处理状态 |
| created_at | TIMESTAMP | 申请时间 |

### 5.4 v4.0.0 新增业务数据表

#### 表 19：user_memories（长期记忆表，Ultra-Memory 确定性等价物）

| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| student_id | VARCHAR(64) | 复合主键（联合 memory_key）；主体标识 |
| memory_key | VARCHAR(50) | 复合主键；白名单键（research_interests / 六维 / hard_constraints / portrait_confirmed） |
| memory_value | JSON | 事实文本（已确认画像白名单投影） |
| source | VARCHAR(30) | 写入来源（portrait_confirmed） |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间（重新确认即覆盖） |

写入门禁（红线）：**只写已确认画像白名单字段**，未确认猜测绝不写；写入触发点仅
`interview.answer_session` 确认分支与 `confirm_profile`（均在确认门通过之后）。

> 完整迁移链见 `backend/alembic/versions/`（0001-0014：0013 dialogue_sessions /
> 0014 user_memories）；以上为业务语义摘要，字段以 ORM 模型为准。

---

## 6. API 接口文档 (API Documentation)

### 6.1 外部大模型接口

接入"清小搭"统一基座网关，支持模型路由分发与故障降级。

#### 6.1.1 LLM 对话接口

- 接口地址：`POST /api/v1/llm/chat`
- 请求体示例：

```json
{
  "model": "glm-5-turbo",
  "messages": [],
  "stream": true
}
```

- 说明：支持流式输出，用于对话问答、问卷生成、简历打磨、推荐理由生成等场景；生产环境固定单 provider（智谱 GLM），密钥经只读文件注入。

#### 6.1.2 向量嵌入接口

- 接口地址：`POST /api/v1/llm/embeddings`
- 说明：用于论文摘要、导师简介、简历内容的向量化，支撑向量检索与匹配计算。

### 6.2 校内数据源接口

需申请校内网关权限，对接清华校内官方数据能力。

| 接口名称 | 方法 | 接口路径 | 说明 |
| :--- | :--- | :--- | :--- |
| 学生身份认证 | GET | /api/tsinghua/auth/verify?token={jwt} | 校验学生身份与权限 |
| 图书馆论文检索 | GET | /api/tsinghua/lib/papers?author_id={advisor_id}&years=2 | 获取导师指定年限内的论文列表 |
| 院系师资爬虫触发 | POST | /api/internal/scrape/faculty | 传入师资页面URL，异步返回抓取的导师数据 |

### 6.3 业务功能接口汇总

| 接口名称 | 方法 | 接口路径 | 说明 |
| :--- | :--- | :--- | :--- |
| 导师匹配 | POST | /api/match | LLM 语义+向量契合度综合匹配，返回推荐列表 |
| 导师列表查询 | GET | /api/mentors | 返回导师基础信息，含热门指数、行业性质扩展字段 |
| 导师排序 | GET | /api/mentors/sort?metric={indicator} | 按指定指标降序重排导师列表，支持7项指标 |
| 散点图数据 | GET | /api/scatter | 返回散点图所需的热门指数与行业性质数据 |
| 动态访谈（OpenAI 协议） | POST | /api/v1/chat/completions | 清小搭入口；含表达层增强（失败降级） |
| 兴趣探索 | GET/POST | /api/interest-exploration/* | 研究场景问卷 + 候选方向 apply |
| 招募信息 | GET/POST | /api/recruitments | 获取招募列表 / 发布新招募 |
| 招募评论 | GET/POST/DELETE | /api/recruitments/{id}/comments | 评论 + 点赞 + 举报 |
| 导师评分 | GET/POST | /api/advisors/{id}/ratings | 六维主观评分与聚合（≥8 样本阈值） |
| 简历生成打磨 | POST | /api/resume/generate | 调用大模型生成或优化简历内容 |
| 简历投递 | POST | /api/resume/submit | 向指定招募投递简历 |
| 评价反馈 | POST | /api/feedback | 提交导师评价与反馈，入库用于迭代 |
| 模型训练触发 | POST | /api/train/trigger | 管理员触发模型重训练，更新匹配算法权重 |

### 6.4 导师服务接口（v3.0）

| 接口名称 | 方法 | 接口路径 | 说明 |
| :--- | :--- | :--- | :--- |
| 验证码登录 | POST | /api/mentor/auth/* | 清华邮箱验证码登录/登出/会话 |
| 校园卡核验 | POST | /api/mentor/verification/* | 导师身份核验（脱敏卡号） |
| 档案认领 | POST | /api/mentor/claim/* | 认领治理档案 |
| 档案读写 | GET/PATCH | /api/mentor/* | 档案查看、字段级编辑（进审批） |
| 意向中心 | GET | /api/mentor/inbound | 学生站内投递收件箱 |
| 导师招募 | GET/POST | /api/mentor/recruitments | 导师侧招募管理 |
| 隐私控制 | GET/POST | /api/mentor/privacy/* | 隐私设置 / 下架申请 |
| 管理审批 | GET/POST | /api/admin/mentor/* | 档案编辑与发布审批（管理员鉴权） |

---

## 7. 测试计划 (Test Plan)

### 7.1 测试策略

| 测试类型 | 工具选型 | 覆盖范围 |
| :--- | :--- | :--- |
| 单元测试 | pytest | 雷达图面积计算算法、权重归一化逻辑、数据清洗正则表达式 |
| 集成测试 | pytest + httpx | SSO 登录流程、大模型 API 超时重试机制、邮件发送网关连通性 |
| 契约测试 | pytest | OpenAI 协议兼容（QXD 入口）、统一响应封装、鉴权注入 |
| 治理与合规测试 | pytest | 证据治理门（0 记录诚实空态）、私域信息不泄露、secret 治理 |
| Agent 幻觉测试 | 注入测试集 | 验证回答严格基于检索结果，不编造导师联系方式、招生名额等信息 |
| 表达层专项测试 | pytest | LLM 重写生效/降级/探测跳过/确认门与匹配不增强（17 用例） |
| 端到端测试 | Playwright | 完整用户流程自动化验证，覆盖匹配、追问、投递全链路 |

### 7.2 核心测试用例

| 用例 ID | 场景描述 | 预期结果 |
| :--- | :--- | :--- |
| TC-01 | 学生上传一份包含"强化学习"经历的 PDF 简历 | Agent 成功提取关键词，并自动调高"学术敏锐度"维度的需求权重 |
| TC-02 | 学生追问"张教授最近带学生延毕吗？" | Agent 检索知识库中的学生评价/毕业年限数据，客观回答，不恶意揣测 |
| TC-03 | 点击"联系导师"按钮 | 成功唤起邮件客户端，收件人为导师邮箱，发件人为当前登录学生邮箱 |
| TC-04 | 切换移动端视口访问 | 页面自动适配移动端布局，核心功能入口可正常访问 |
| TC-05 | 提交导师评价反馈 | 反馈数据成功入库，对应导师的推荐排序权重同步更新 |
| TC-06 | 访谈进行中，LLM 可用（配 key） | 表达层整段重写回复，输出通过校验闸门（≤400 字、禁词、选项覆盖） |
| TC-07 | 无 LLM key 或 LLM 超时 | 访谈回复逐字降级回固定模板，不伪造模型输出 |
| TC-08 | 画像确认门或匹配结果轮 | 表达层不介入，确定性原文原样返回（诚实性红线） |
| TC-09 | 导师评分样本数不足 8 | 聚合不出值，前端显示"样本不足"，服务层保留原始聚合 |
| TC-10 | 兴趣探索场景多选 | 确定性映射输出稳定 top-5 候选，两次请求结果一致 |

---

## 8. 部署与运维 (Deployment & Operations)

### 8.1 部署环境

- **宿主平台**：清华大学"清小搭"智能体广场（基于校园私有云/容器云）
- **运行环境**：Python 3.10+, Node.js 18+（前端）, Docker
- **基座模型**：智谱 GLM 系列（生产经 `LLM_PROVIDER=glm` + 只读密钥文件注入）

### 8.2 部署步骤

#### 步骤一：环境配置

拉取 Tsing-RADAR 官方镜像，编写 `.env` 配置文件，注入平台分配的密钥与服务地址：

```env
APP_KEY=qingxiaoda-assigned-key
LLM_PROVIDER=glm
LLM_API_KEY_FILE=/run/secrets/llm_api_key
DATABASE_URL=postgresql://tsingradar:***@db:5432/tsingradar
REDIS_URL=redis://redis:6379/0
SMTP_HOST=smtp.tsinghua.edu.cn
```

#### 步骤二：数据初始化

执行数据库迁移脚本，初始化所有数据表结构：

```bash
alembic upgrade head
python scripts/init_data.py
```

#### 步骤三：知识库预热

运行师资采集与治理导入脚本，预加载全校核心院系导师公开信息（默认发布 0 条，须通过发布审核流程导入）：

```bash
python scripts/crawl_faculty.py --all-departments
python scripts/ingest_tsinghua_catalogs.py
```

#### 步骤四：服务注册

将 Agent 注册至"清小搭"智能体广场路由网关，配置域名解析与 SSL 证书，完成上线。

### 8.3 运维注意事项

- **合规性**：爬取校内网页时严格遵守 `robots.txt` 及校内网络中心规定，设置合理的请求延迟，禁止高频并发抓取。
- **数据隔离**：按院系、学生身份（本/硕/博）做数据权限隔离，确保学生仅能查看权限范围内的导师招生与招募信息。
- **监控告警**：配置大模型接口成功率、接口响应时长、数据库连接数核心指标监控，异常时触发告警。

---

## 9. 模型训练与迭代闭环

### 9.1 数据采集链路

系统建立完整的数据回流链路：

1. 问卷会话采集学生需求画像
2. 匹配记录留存推荐结果
3. 反馈表收集学生点赞/点踩与评论
4. 训练样本表记录学生最终选组决策

所有数据脱敏后作为模型训练的特征与标签来源。

### 9.2 训练触发与更新

- 管理员可通过 `/api/train/trigger` 接口触发模型重训练
- 训练完成后新模型权重自动加载至匹配推理路径
- 采用灰度发布机制，小流量验证效果后全量上线

### 9.3 效果评估指标

- 核心指标：推荐准确率（学生最终选择TopN推荐导师的比例）、点赞率、反馈好评率
- 辅助指标：平均对话轮次、简历投递转化率、导师回复率

---

## 10. v3.0 导师服务与表达层增强

### 10.1 版本概览

v3.0 在 v2.2 审计基线之上完成两侧能力整合（`integration/final-20260819`）：

| 能力域 | 内容 | 关键实现 |
| :--- | :--- | :--- |
| 导师服务门户 | 登录/核验/认领/编辑/意向/招募/隐私 | `app/api/v1/mentor_*` 7 个路由模块 + 前端 `/mentor/*` 7 页面 |
| 评分社区 | 六维评分 + ≥8 样本阈值聚合 | `advisor_ratings.py`（API 层过滤）+ `RatingSummary.vue` |
| 兴趣探索 | 8 场景 → 10 方向池 top-5 | `interest_exploration.py` 纯静态映射 |
| 客观四维雷达 | 证据治理数据驱动展示 | `ChartPanel.vue`，无证据不出值 |
| 表达层增强 | LLM 整段重写访谈回复 | `chat_expression.py`，fail-closed 降级 |

### 10.2 表达层增强设计（chat_expression）

```
访谈状态(state) ──build_interview_fact_pack()──▶ 确定性事实包(fact pack)
                                                        │
用户消息 ────────────────────────────────────────────────┤
                                                        ▼
                                            render_interview_reply()
                                            （复用 _llm_complete_result 唯一入口，4s 超时）
                                                        │
                        ┌─────────────────────────────────┼─────────────────────┐
                        ▼                                 ▼                     ▼
                   校验闸门通过                    校验失败/超时/无凭据      诚实性红线轮次
                   （重写文本生效）                 （逐字降级固定模板）   （确认门/匹配不增强）
```

**校验闸门**：非空 / ≤400 字 / 禁词（画像已确认、匹配完成等）/ 全部选项 label 覆盖 / 题面核心片段（≥6 字）覆盖。任何一项不过即降级，保证不改变访谈语义结构。

**红线**：`needs_confirmation`（画像确认门）与 `recommend_ready`（匹配结果）不进入表达层；平台探测请求（`max_tokens:1`）跳过；零新增配置（复用 GLM_*/LLM_TIMEOUT）。

### 10.3 评分聚合样本阈值

- 服务层（`advisor_rating.py`）物化聚合保留原始 `{dim}_value/{dim}_n`，不做样本过滤。
- API 层（`advisor_ratings.py`，`ADVISOR_RATING_MIN_SAMPLES=8`）过滤 `n < 8` 的维度值。
- 前端（`RatingSummary.vue`）统一以 8 为阈值口径展示"样本不足"。
- 该分层保证：阈值调整不动数据层；原始聚合始终可审计。

### 10.4 生产部署要点（v3.0 增量）

- 生产强制 `MAIL_MODE=smtp`，邮件密码仅经 `MAIL_PASSWORD_FILE` 挂载（禁止环境变量明文）。
- 边缘路由白名单（`public-route-allowlist.json` + `web-api.caddy`）需覆盖导师服务与评分/兴趣探索全部新路由。
- 清小搭三层链路：`qxd.tsingradar.com.cn` → Caddy edge → qxd-gateway(nginx) → backend:8000；OpenAI 兼容入口 `https://qxd.tsingradar.com.cn/v1`。
- 迁移链至 0012（mentor_campus_card）；升级前按 RUNBOOK 完成数据库备份与 advisory lock 流程。

---

## 11. v3.1 纯对话升级（v2.5 规格）

> 分支 `feature/v25-dialogue`。在清小搭纯对话入口落地 v2.5 规格：简历生成与优化、科研招募信息、对话智能度、纯对话文本化转译、套磁/FAQ 咨询、匹配输出 v2.5 格式。延续"确定性状态机 + LLM fail-closed + 诚实空态"基调。

### 11.1 版本概览

| 能力域 | 内容 | 关键实现 |
| :--- | :--- | :--- |
| 对话智能基座 | 意图分类 + 口语→维度映射 + 隐式关注识别 | `dialogue_intent.py`（DialogueMode 枚举优先级：定向 > 优化 > 从零 > 招募 > 四象限 > 套磁 > FAQ） |
| 状态持久化 | 跨轮对话模式状态 | `dialogue_state.py` + 迁移 0013 `dialogue_sessions`（session_id/student_id/mode/state JSON/version） |
| 简历对话 | 从零生成 / 优化已有 / 定向优化 | `resume_dialogue.py`（6 字段分步采集 → Markdown，PDF 诚实降级） |
| 招募对话 | 自然语言筛选 + 个性化推荐 | `recruitment_dialogue.py`（复用 `list_public_recruitments` 合并口径） |
| 纯对话转译 | 四象限 / 六维对比文本化 | `scatter_dialogue.py` + `match_application.py`（`format_match_outcome` 向后兼容） |
| 咨询/FAQ | 套磁邮件 + 平台 FAQ + 诚实空态 | `consultation.py` |

### 11.2 对话模式分发（chat.py）

```
请求进入 generate_agent_reply
        │
        ▼
探针（max_tokens:1）？────────── 是 ──▶ 不进入任何对话模式（隔离）
        │ 否
        ▼
活动模式存在（dialogue_sessions 有当前会话键记录）？
        │ 是 ──▶ 活动模式优先（防简历字段答案被新意图劫持，如"做过科研助理"）
        │ 否
        ▼
classify_dialogue_intent(最近一轮用户消息) ──▶ 七类对话模式 or NONE
        │ NONE
        ▼
原访谈状态机（answer_session → 表达层 → 匹配）零改动
```

- 分发成功：返回 `stage="dialogue"` 的 AgentReply，reasoning 档位固定为"正在为你检索并整理信息…"（检索档，不冒充模型推理）。
- 画像复用：访谈 portrait（研究兴趣/硬约束）+ 对话中提取信息共用，不重复提问。
- 探测请求与试聊兼容模式保持原语义。

### 11.3 简历对话模块

- **从零生成**：`FIELD_SEQUENCE` 6 字段（姓名/院系/教育/项目/荣誉与任职/补充）逐轮采集，状态存 `dialogue_sessions`；完成后确定性渲染 Markdown 简历（标注"未经真实性核验"，空字段不渲染章节）；PDF 交付诚实降级——平台短时公开转存（`issue_delivery_grant` `qxd_platform`）仅允许匹配报告，聊天内不尝试越权签发简历附件，引导 Web 端简历中心生成下载；投递确认是终局动作（成功或诚实说明后均清状态）。
- **智能预填**（v3.1.1）：触发消息或任一采集轮一次性给出的信息 → `_try_prefill_fields` 抽取为字段，只问缺失项。LLM 优先（fail-closed：无凭据/异常/非 JSON/非空字段 <2 均返回 None），确定性锚点兜底（按标点拆句，姓名前缀正则提取并拒绝含结构词的候选，其余字段按 院系→教育→项目→荣誉→补充 锚点优先级整句归类，只取明确提供的信息）；推进逻辑为"下一个未答字段"（`_next_missing_step`，`key not in fields` 判定，与空答案跳过语义兼容）；引导文案支持"一次说完所有信息"；宽泛回答（随便/都行/不知道…）留空跳过不追问。
- **优化已有**：命令式触发词（优化简历/润色/打磨…）→ 等待粘贴；消息本身即内容 → 直接润色。LLM 三维润色（学术表述/经历量化/逻辑结构）fail-closed 降级确定性整理，绝不虚构经历。
- **岗位要求联动**（v3.1.2）：定向目标经 `resolve_recruitment_target` 解析为公开岗位时，岗位标题成为目标、公开核心要求进入 LLM 提示词（`_polish_user_content`）；无 LLM/解析失败按普通目标名处理。
- **完整性体检**（v3.1.2）：`_finalize_build` 生成后 `_completeness_tips` 检查关键缺失（科研/项目经历、联系方式、教育背景），输出"📋 简历体检"诚实建议（"建议补充…"），不虚构补写。
- **定向优化**：`parse_target_from_message` 提取目标（"针对 XX 老师的课题组" → 姓名 "XX"；岗位类保留原文），透传润色管线。

### 11.4 招募对话增强

- 自然语言筛选：院系别名表（"计算机"→计算机科学与技术系）、类型关键词（科研助理/实习生/助研…）、急招标记（急招/尽快/近期…）、方向关键词（NLP/强化学习…）→ 确定性过滤。
- **方向别名归一化**（v3.1.1）：`DIRECTION_ALIASES` 14 组双向映射（NLP↔自然语言处理、LLM↔大模型、RL↔强化学习、AI↔人工智能…），解析、过滤、画像兴趣匹配、相关度排序统一走 `_matches_direction` 同义词组匹配；纯英文缩写按词边界匹配（`(?<![A-Za-z0-9])`，防 "AI" 误命中 training）；兴趣命中输出归一化规范词并去重。
- **宽泛问题引导**（v3.1.1）：无任何筛选条件（`_is_vague_query`）且有在招记录时——有画像按研究兴趣排序推荐并附"院系/类型/方向"筛选引导，无画像给引导后展示最新在招概览；无在招记录保持诚实空态（不追加引导、不伪造热门推荐）。
- **筛选偏好跨轮记忆**（v3.1.2）：明确筛选条件写入 `dialogue_sessions`（mode=recruitment_query，`_save_filter_memo`）；宽泛查询自动沿用（`_load_filter_memo`，mode 用 `get_dialogue_mode` 判定），回复前缀说明"我沿用你之前提到的筛选条件…"；新条件整体替换旧记忆；无记忆回落到宽泛引导。
- **岗位详情追问**（v3.1.2）：意图分类新增"岗位/招聘/工作机会"触发词与「第 N 个」指代正则（`dialogue_intent.py`）；`_parse_ordinal` 支持阿拉伯/中文数字（含十位）；`_is_detail_query` 排除优化/投递语义；`format_recruitment_detail_v25` 输出完整详情 + 距截止天数（`_deadline_remaining`，无明确截止不编造）；序号越界诚实提示。
- **岗位联动定向优化**（v3.1.2）：`resolve_recruitment_target` 按 序号（与 digest 同口径 `_sort_records` 排序，可传画像兴趣）→ recruit_id → 标题/检索文本子串 解析为公开岗位；`resume_dialogue.handle_resume_polish` 解析成功后把岗位标题设为目标、公开核心要求附加进 LLM 提示词（`_polish_user_content`，明确"不得虚构经历"）；无 LLM/解析失败按普通目标名处理。
- 个性化推荐：画像 `research_interests` 与岗位方向重合数 → 推荐指数（★，1+命中数，上限 5）；输出对齐 v2.5 摘要格式（发布方·院系 / 类型|截止 / 核心要求 90 字摘要 / 投递说明 / 推荐理由）。
- 诚实空态：无通过审核且在招期内的记录 → "暂无通过审核且仍在招期内的招募信息" + 官网 URL，不编造；无重合 → "没有与你的研究兴趣直接重合的在招岗位"。
- 静态记录补全 `dept`/`publisher_name`（数据治理后置）。

### 11.5 纯对话文本化转译

- **四象限**：以已审核客观证据（项目广度 × 主题广度，`QUADRANT_HOT_THRESHOLD=60` 严格大于）分类为 双高活跃/项目驱动型/主题探索型/聚焦深耕型；体制属性（国/私）与热门度属历史推断字段，已按治理门禁剥离，明确标注不公开；评分门未开 → 诚实空态"暂不能诚实地进行四象限分类"。
- **六维对比表**（匹配输出 v2.5）：用户侧需求为画像映射推导值（明确标注"需求映射"，含隐式关注维度 75 分），导师侧为匿名评价 ≥8 样本聚合值；无样本 → "暂无足够样本"，无收录评价 → "未收录评价"。`format_match_outcome` 新增参数全部可选，向后兼容 Web 端调用。

### 11.6 咨询与 FAQ

- **套磁邮件**：确定性模板（问候/自我介绍/研究兴趣/对导师工作的理解/礼貌收尾）+ LLM 增强（失败降级）；联系方式占位"以官网公布为准"；姓名规范化（单字姓氏 + "老师"后缀）。
- **平台机制 FAQ**（怎么匹配/如何开始/雷达图是什么/怎么投递/怎么选导师）→ 确定性答案。
- **导师个体情况**（组会/延毕/毕业难度/招生名额/学生评价/风评/实验室氛围）→ 知识库无收录数据时诚实提示"该信息暂未收录经过核实的公开数据"，建议通过导师官网或官方邮箱确认；绝不编造。

### 11.7 诚实性红线与数据治理

- 六维主观：匿名 1-5 分，`ADVISOR_RATING_MIN_SAMPLES=8` 门控（API 层过滤 + 服务层 `get_gated_summary`）；客观四维：`public_score_bundles` 门控。
- `popularity`（D1 禁止字段）与 `sector`（legacy/inferred）不参与对话层输出；LLM 全部 fail-closed（无凭据/provider≠glm/异常 → 确定性降级）；不编造联系方式、名额、评价；简历只整理用户提供信息。
- 状态写入即提交（与 `interview.py` 惯例一致），跨请求会话键复用依赖此提交。

### 11.8 迁移与验证

- 迁移链至 **0013**（dialogue_sessions）；升级前按 RUNBOOK 完成备份与 advisory lock 流程。
- 后端全量：**622 passed / 5 failed / 2 skipped / 2 errors**（失败集与 v3.0 基线一致，均为 Windows 环境性：迁移 L3、CJK 字体、LLM secret 权限/symlink）。
- v2.5 专项 69 用例（意图 7 / 简历 18 / 招募 18 / 四象限 5 / 咨询 8 / 匹配格式 7 / 对话黑盒 6）全绿；v3.1.2 新增 8 用例（序号解析与详情判定 / 第 N 个详情 / 序号越界诚实 / 条件记忆沿用 / 新条件替换 / 岗位解析 / 体检提示 / 岗位要求进提示词）；v3.1.3 新增 9 用例（真人口语变体 27 条子断言 / 简历粘贴启发式正反 / 雷达图 FAQ 变体 / 评分文件损坏降级 / render_radar_text 确定性·零满量程·轴序 / 附件禁用文本雷达图黑盒）；黑盒用例含"探针不进入对话模式""活动模式优先""reasoning 检索档位""诚实空态无 x_soda"。

### 11.9 v3.1.3：真人口语实测 + 仅对话端口雷达图

> 触发：对清小搭纯对话入口做"正常人说法"全面复测（意图层 51 例扫描 + 回复层 10 场景 + 黑盒链路），修复全部真实漏匹配；并把雷达图从"附件能力"扩展到"仅对话端口直出文本字符版"。

#### 11.9.1 意图触发词真人口语扩充（dialogue_intent.py）

- 定向优化新增：优化下/优化一下/润色下/润色一下/改改/提高/改进/看看简历/改简历/优化简历…（避开裸"优化"，防"性能优化"访谈答案劫持）。
- 从零生成新增：帮我写简历/做一份/整一份/简历怎么做/怎么写简历/从零写/新建简历…
- 优化已有新增：粘贴原文触发（`_RESUME_PASTE_ANCHORS` 完整字段锚点 ≥2 命中 + 长度 ≥60 → RESUME_POLISH，`_looks_like_resume_paste`）；"我之前那段/这段经历"续聊。
- 招募新增：招人吗/在招/急招/实习机会/实习吗/实习岗位/科研岗位/岗位/工作机会…
- FAQ 新增：咋弄/怎么办/干嘛的/是啥/有什么用/怎么用/能干嘛…
- 四象限/套磁补充口语变体（看看哪些方向热/热门方向/私企/国企…、发邮件/给老师写信…）。
- 边界护栏（防访谈误伤，均为刻意不加的裸词）：实习（保留"实习经历"→访谈）、优化（裸词）、热门（裸词）、材料/化学/物理（裸词，防"我找了材料来分析"）。已知边界："找大模型相关的"（依赖 memo/active_mode 上下文延续）。
- 测试：`test_dialogue_intent_natural_language_variants` 27 用例（含非路由防护断言）。

#### 11.9.2 文本版雷达图（仅对话端口直出）

- 动机：清小搭纯对话端口无附件能力，`QXD_ATTACHMENTS_ENABLED` 关闭或 `assert_qxd_delivery_ready` 未就绪时，旧行为只给文本表格（无图）。
- 实现（`radar_chart.py`）：`render_radar_text(series, labels, title, sample_note)`——
  - 多边形：canvas 25×13、中心 (12,6)、半径 (12,6)（字符宽高比约 2:1，视觉接近正菱形）；4 轴方位 0 上/1 右/2 下/3 左，与 `OBJECTIVE_DIMENSION_KEYS` 轴序一致；网格环用 `·`，数据多边形用 Bresenham 直线 + 射线法多边形包含填充 `█`。
  - 数值条形：每维一行，20 格 `█`/`░`（满格 100），如 `项目广度  ██████████████████░░  88`。
  - 诚实性：值 0 → 中心点 + 空条（不画"基准 50"冒充）；值 100 → 满格菱形。
- 接入（`chat.py::_radar_intent_reply`）：三分支——有已审核评分且附件可用 → SVG 附件（`issue_radar_chart_token` + `SodaAttachment`）；附件未启用 → 文本版 + "仅对话端口直出，数据与附件版同一来源" + `样本来源：已审核评分发布 v{release_version}`；交付未就绪（`assert_qxd_delivery_ready` 抛 4xx）→ 文本版。两个文本分支都保留"客观指标与匿名主观评价严格分离，本图不含学生评价"声明与官网交互式雷达图引导；评分门未开/无 bundle → 诚实空态 + 四维文本表格（`_radar_text_table`）。
- 安全：文本版走对话文本直出，不签发任何附件 token，无新增对外端点；附件路径继续走无状态 `/v1/radar/{token}`（短时签名）。
- 测试：`test_radar_chart.py` 新增 3 项（确定性 + 包含图表与数值 / 全 0 诚实空态 / 轴序对齐）；`test_qxd_contract.py` 新增黑盒 `test_qxd_radar_intent_text_chart_when_attachments_disabled`（monkeypatch `QXD_ATTACHMENTS_ENABLED=False` → 断言字符条形 `█`、四维标签、数值、分离声明、`x_soda` 不存在）。

#### 11.9.3 健壮性与文案修复

- **评分文件损坏诚实降级**（`mentor_score_governance.load_score_dataset`）：`MentorScoreDataset.model_validate_json` 捕获 `ValidationError` → `logger.exception("mentor_score_dataset_invalid")` + 返回 None（诚实空态），不再让雷达/评分链路 500；sha256 校验失败仍 RuntimeError（发布门语义）。
- **简历首轮引导去重**（`resume_dialogue.py`）：`FIELD_SEQUENCE[0][1]` 精简为 "第一步：你的姓名是？"，不再与 `_start_or_resume_build` 引导语重复。
- **FAQ 顺序修正**（`consultation.py`）："简历"条目移到"投递流程"之后（防拦截"怎么投递简历"）；雷达图 FAQ 主题改"雷达图"以命中"是啥/干嘛的/有什么用"。
- **测试环境隔离**（`conftest.py`）：强制清空 `MENTOR_SCORE_DATA_FILE`/`MENTOR_SCORE_DATA_EXPECTED_SHA256`，防本机 .env 旧 schema 评分文件污染测试进程。


---

### 11.10 v3.1.4：竞品优势内化 —— 科研风格速测 + 方向地图 + 画像确认增强

> 背景：浏览器实测竞品"清研向导"（清小搭广场主要竞争产品）完整工作流——8 字段表单 → 16 题科研风格测试 → 画像摘要+3 追问 → 画像确认门 → 院系方向地图 → 导师筛选 → 联系准备（邮件/论文阅读清单/面谈问题）。其核心卖点是"结构化渐进引导 + 轻量自我认知 + 确认后再推进"，且明确声明"不判断你是否适合科研，也不评价能力高低"。v3.1.4 把这三项优势内化为我们的确定性版本，同时守住项目红线（不编造、不评价、不越数据治理边界）。

#### 11.10.1 科研风格速测（research_style.py，新）

- **设计取舍**：竞品是 16 题 LLM 判定，我们做成 **4 题确定性规则表分类**——范围（broad/deep/mixed）、推进方式（problem/method/data）、形态（theory/engineering/balanced）、成果偏好（paper/system/analysis），答案用序号或选项文字匹配（序号精确匹配，"11" 不误中 "1"）。`_CORE_STYLES` 9 组「形态 × 驱动」组合 → 名称 + 通俗解释（问题溯源型 / 理论建构型 / 现象洞察型 / 落地攻坚型 / 方法工程型 / 数据驱动型 / 问题牵引型 / 方法探索型 / 实证归纳型），范围修饰拼前缀（多线· / 深耕·）。零 LLM 依赖 → 结果可复现可测试。
- **诚实红线**：welcome 与结果均含"不判断你是否适合科研，也不评价能力高低"（与竞品措辞对齐，避免制造"你很弱/你很适合"暗示）；结果只作偏好参考，**不写入六维导师评分**，仅提示"偏好形态可回填画像 research_mode（theory/engineering/mixed），「确认」后生效"。
- **多轮状态机**：`dialogue_sessions`（mode=research_style，step + answers），「取消/不测了」→ 清除状态退出；非法答案同题重试不推进；答完自动清除状态（可再触发重测）。触发消息即答案时也从第一题正常走。
- **意图接入**（`dialogue_intent.py`）：`RESEARCH_STYLE` 触发词含"科研风格/风格测试/测测我/我适合做什么方向/了解自己"等；分类优先级位于套磁之后、FAQ 之前；"测测我"（自我认知）先于"什么方向"（方向地图）判定。

#### 11.10.2 研究方向地图（direction_map.py，新）

- **内容**：16 个公开学科方向（大模型/NLP/视觉/ML/RL/机器人/系统/网络/数据库/芯片/通信/理论计算/材料化学生物/生物信息/新能源/控制优化仿真），每条 = 规范名 + 一句话说明 + 示例关键词；34 项别名归一（NLP↔自然语言处理、LLM↔大模型、自动驾驶↔机器人 等，与 `recruitment_dialogue.DIRECTION_ALIASES` 口径打通）。
- **治理边界（D1）**：只输出学科方向本身，**刻意不输出参考教师名单**——教师-方向绑定属非公开数据治理范围，知识库无证据时不编造；渲染文本含"不涉及具体导师"。`resolve_direction` 别名未命中返回 None（词面匹配，不做语义推断）。
- **防访谈误伤**：触发词刻意用完整问句结构（"有哪些方向/方向怎么选/这个系有什么方向"），不引入裸词"方向"；"我研究方向是自然语言处理"（访谈自述）不被拦截，仍归访谈。

#### 11.10.3 画像确认增强（interview.py `_summary`）

- "匹配时将重点考虑"行：聚合研究兴趣/研究方式/生涯方向/指导偏好/硬性条件，无信息时诚实写"暂无已确认信息，先匹配会较宽泛"。
- "尚未明确（可选补充）"行：draft_hard_constraints 的 confirmation_prompt + unresolved 去重 + research_mode/career_orientation 未确认时补两条引导；全无时诚实写"无"。
- "确认画像"口令与既有断言（"已确认硬性条件"）完全兼容，不破坏旧流程。

#### 11.10.4 迁移与验证

- 后端全量：**638 passed / 5 failed / 2 skipped / 2 errors**（新增 16 用例全绿：`test_research_style.py` 10 项 + 意图触发词/优先级/防拦截 3 项 + 契约黑盒 3 项；失败集与 v3.1.0 基线逐项一致，均为 Windows 环境性）。
- 科研风格速测：确定性（同答案同结果）、mode 三态映射、序号精确匹配、4 轮全流程、取消退出、非法重试不推进。
- 方向地图：16 方向全列出、方向名唯一、渲染不含"参考教师"、别名命中/未收录 None。
- 黑盒：科研风格多轮直出（无 x_soda 附件、不触碰访谈状态机 `QuestionnaireSession` 0 记录）、取消后可再触发其它模式、方向地图单轮直出。

---

### 11.11 v3.1.5：雷达边缘线图勾连 + 特色「契合度构成分解」

> 背景：①用户指定雷达图由颜色填充改为边缘线图勾连（不填充、只描边连顶点）；②在竞品对比中确立我们的特色——清研向导明确"不判断是否适合科研、不评价能力高低"，回避量化；而我们给出**可解释的量化契合度**：不仅报总分，还倒推"为什么是 XX 分"的维度构成。

#### 11.11.1 雷达图边缘线图勾连（四端口同步）

- **SVG**（`radar_chart.render_radar_svg`）：数据系列 `<polygon>` 由 `fill="{color}" fill-opacity="0.45"` 改为 **`fill="none"`**（保留 `stroke` 2.5px 与虚线分支），并新增**顶点勾连点** `<circle r="3" fill="{color}">`（单系列 4 个）；图例 `<rect>` 同步无填充。删除死常量 `ADVISOR_TRAIT_FILL_OPACITY`。
- **文本版**（`_render_text_polygon`）：删除多边形内部 `█` 填充循环（`_point_in_poly` 随之移除），只保留 `█` 边缘描边——仅对话端口直出的文本雷达同样"线勾连"；逐维数值条形（█/░）不受影响。
- **PDF**（`render_radar_drawing`）：reportlab `Polygon(fillColor=Color(alpha=0.45))` → **`fillColor=None`**。
- **前端**（`useRadarOption.ts`）：删除 ECharts series 的 `areaStyle` 与 `RadarSeries.areaColor` 字段、四组配色常量的 `areaColor`；`variables.scss` 清理填充色变量（保留描边色）。`splitArea` 网格背景保留（坐标背景，非数据填充）。

#### 11.11.2 契合度构成分解（match_application.py）

- 新增 `format_fit_breakdown(item) -> str | None`：读取 `item["score_breakdown"]`（matching.py 已算好的逐排序目标 breakdown：`score 0-1 × 权重 × 置信度`），输出「契合度构成」块，按固定枚举序（确定性）给每个目标一行：
  - `▲ 拉高`：该维得分×100 比 fit_score 高 ≥3 分；`▼ 拉低`：低 ≥3 分；其余 `· 中位`；
  - `score is None`（画像无该维度证据）→ `未计入（画像无该维度证据，确认后生效）`——诚实，绝不用基准值冒充；
  - 每行附权重（requested_weight%）与得分；标题带诚实声明"由排序分数倒推，与保守排序分同一口径，非新增评分"。
- 接入 `format_match_outcome`：候选头部行（"契合度 XX 分；保守排序分…"）之后输出；breakdown 缺失/为空 → 返回 None 省略该块（旧数据与既有测试零破坏）。
- 六目标中文标签：topic_fit→方向匹配、research_mode_fit→研究方式、mentorship_fit→指导方式、career_fit→生涯去向、innovation_fit→创新偏好、opportunity_fit→招募机会；未知目标回退原始键不崩溃。

#### 11.11.3 迁移与验证

- 后端全量：**645 passed / 5 failed / 2 skipped / 2 errors**（新增 7 用例全绿：雷达线图 1 + 构成分解单测 4 + 黑盒 2；失败集与 v3.1.0 基线逐项一致，均为 Windows 环境性）。
- 雷达线图：SVG `fill="none"` 计数 7（网格5+数据1+图例1）、无 `fill-opacity`、顶点 `<circle>` 4 个；文本版满值多边形边缘 48 格 < 上界 80（内部填充会 >120）；reportlab 数据多边形 `fillColor is None`。
- 构成分解：拉高/拉低/中位/未计入四类行、阈值边界（±3 含）、确定性、缺失 breakdown → None、未知目标回退；黑盒验证对话端口输出构成块与无 breakdown 时的诚实省略。
- 前端：`npm run type-check` 与 `npm run build` 均通过。

### 11.12 v3.1.6：对话闭环 —— 匹配后候选追问 + 探索结果回填画像

> 背景：把已有特色模块（雷达图 / 契合度构成分解 / 科研风格速测 / 方向地图 / 套磁邮件）串成**有上下文记忆、可追问、可回填的对话闭环**。三处均为"说了但不生效/没有下文"的断点：①匹配结果后说「第 N 个」会被招募序号解析抢走，到不了匹配候选；②风格速测结果写"「确认」后生效"但从未回填；③方向地图选方向后没有下文（`resolve_direction` 生产代码零调用）。全部为**确定性实现**，不新增 LLM 依赖，fail-closed 与诚实性红线不变。

#### 11.12.1 匹配后「第 N 个」候选追问（上下文延续）

- **序号短路**（chat.py 分发预检）：`_resolve_dialogue_intent` 前先 `_parse_ordinal(latest_user)`（复用 `recruitment_dialogue.py` 的解析，阿拉伯/中文数字）；仅当 `_ordinal_follows_match_results` 为真（会话存在、student_id 匹配、`status == CONFIRMED`；或本请求前序消息含 `_CONFIRM_SIGNALS`，覆盖"同一请求内先确认后追问"边缘）时把意图置为 `NONE`，放行到匹配候选分派——**未确认会话的招募序号照常工作**。
- **候选分派**（recommend_ready 分支，`_RADAR_INTENTS` 之后、`_RECRUITMENT_INTENTS` 之前）：越界 → 诚实提示"当前匹配结果只有 N 位候选（第 1 到第 N）"；套磁词（`_CONSULT_EMAIL_TERMS` 命中）→ `handle_consult_email(latest_user=f"给{name}写一封套磁邮件")` 注入目标导师；雷达词 → 走 `_radar_intent_reply` 的 ordinal 定位；其它 → `"第 N 位候选详情：" + format_match_item(item, index=N, ...)`。
- **`format_match_item` 抽取**（match_application.py）：`format_match_outcome` L304-362 的 per-item 块逐字搬出为 `format_match_item(item, *, index, profile, advisor_ratings, user_dimension_scores)`，循环调用——**内联输出逐字不变**，老测试零破坏；对比测试断言 `full.count(item_block) == 1`。
- **雷达图按序号选候选**（`_select_radar_item`）：优先级 姓名点名 > ordinal 定位（越界/无 bundle → None）> 首位兜底；点名目标无已审核评分时诚实空态（"{name} 暂无已审核客观评分"），无名候选保持既有文案。
- **自动引导升级**：匹配结果后追加"可以继续追问：- 「第 N 个」查看候选详情 / - 「第 N 个的雷达图」/ - 「第 N 个的套磁邮件」"；雷达可用时再追加"或直接回复「雷达图」查看首位候选"；条件含 `_parse_ordinal(latest_user) is None`（不打断追问轮）。

#### 11.12.2 科研风格速测「确认」回填 research_mode

- **`upsert_portrait_field`**（interview.py，对话端口专用）：无 `expected_version` 冲突检查、内部自增 `profile_version`；`research_interests` 键**合并去重**（保持既有顺序、上限 8）且原 `interest_statement` 为空时自动补"我对…方向感兴趣。"；走 `_set_state_after_profile_change`——已确认画像被改动 → 状态回落 `awaiting_confirmation`（需重新确认，与既有 patch_profile 语义一致，诚实红线不变）。
- **风格 pending 状态机**（research_style.py，`handle_research_style` 返回类型 `str | None`）：答完 4 题**不再 clear**，保留 `{"step": 4, "answers": [...], "pending": True}`；下一轮 pending 分支：确认词（`确认/生效/确定/可以` 等）→ `classify_style(answers)["mode"]` 回填 `research_mode` + clear + "已回填研究方式：X"文案；取消词 → clear + 放弃文案；风格触发词 → 重置 step=0 重测；导航词（匹配/招募/方向地图/套磁等）→ clear + `return None` 放行到主流程；其它 → **保持 pending** + 简短 nudge——防止"匹配导师"等短词掉进未确认访谈被误当答案。
- `_style_result_text` 末尾明示下一步："回复「确认」回填到画像；回复「取消」放弃；直接说「匹配」「招募」或「方向地图」继续。"

#### 11.12.3 方向地图选方向 → 回填 research_interests + 引导

- **状态化 handler**（direction_map.py，`MODE_DIRECTION_MAP = "direction_map"`，`handle_direction_map(...) -> str | None`）：首轮触发 upsert 模式 + 渲染地图；下一轮 `resolve_direction` 命中 → `upsert_portrait_field({"research_interests": [canonical]})`（内部合并去重）→ clear → "已记录研究方向：X…回复「确认画像」或「招募」"；取消词 → clear + 退出文案；未命中 → clear + `return None`（**单次拦截**：放行走访谈，保住"我研究方向是…"这类访谈自述不被吞）。
- `resolve_direction` 补规范名全名比对（别名未命中时再与 `DIRECTION_MAP_DATA` 规范名小写比对，回复完整规范名也应命中）。
- **治理边界不变**：只回填方向本身，不涉及教师名单（D1 红线）。

#### 11.12.4 对话释放同步守卫（潜伏 bug 修复）

- 对话模式消费的轮次**不持久化**到 `questionnaire_sessions`；若对话模式释放后仍用全量历史走 `sync_user_transcript`，会把"测测我 / 1 / 2"等重放进访谈。修复：`dialogue_released` 标记——意图命中对话模式即置位，dispatch 返回 None 时只同步 `[latest_user_turn]`，未释放走原全量逻辑。简历模式同暴露，一并覆盖。

#### 11.12.5 迁移与验证

- 后端全量：**662 passed / 5 failed / 2 skipped / 2 errors**（新增 17 用例全绿：序号候选追问 4 + 雷达按序号 1 + 套磁注入 1 + 越界诚实 1 + 风格确认/取消/重测/nudge/放行 5 + 方向回填/全名/未命中/取消 4 + 单候选对比 1 + upsert 3；失败集与 v3.1.0 基线逐项一致，均为 Windows 环境性）。
- 序号短路仅作用于已确认会话：未确认会话的招募序号照常；回填触发重新确认是既有 patch_profile 语义，非新行为。
- 不新增 LLM 依赖、不触碰评分门禁与 D1 治理字段（popularity/sector 仍禁止）。
- 前端：`npm run type-check` 与 `npm run build` 均通过。

### 11.13 v3.1.7：匹配后二次筛选 + 候选详情升级（对标清研向导实测短板）

> 背景：浏览器实测清小搭平台竞品"清研向导"后蒸馏三条可吸收项——①它匹配后提供**「换一批」（排除已展示）与「缩小范围」（A/B/C/D 结构化追问→重筛）**，我们缺这个二次筛选闭环；②它每位候选给**「需要补充的知识或技能」（能力差距分析）**与**可点击官方主页链接**，我们缺差距分析、主页链接未渲染；③它匹配结果纯文本、无雷达无评分，**量化契合度 + 雷达仍是我们的唯一优势**，继续打透（候选六维对比升级 10 格条形可视化）。全部**确定性实现**，不新增 LLM 依赖，fail-closed 与诚实性红线不变。

#### 11.13.1 匹配结果二次筛选（match_refine.py，新服务）

- **状态机**（照抄 research_style pending 模式）：`handle_match_refine(db, *, latest_user, session_id, student_id, structural_match=False) -> str | None`；None = 释放回主流程。状态持久化在 `dialogue_sessions.state`（mode=`match_refine`）：`{"step": null|"include"|"exclude", "excluded_advisor_ids": [...], "topic_include": [...], "topic_exclude": [...], "last_shown_advisor_ids": [...]}`。
- **触发**（仅 recommend_ready 上下文，`chat.py` 分发预检）：`get_dialogue_mode == match_refine` 或 `_REFINE_TRIGGERS` 命中（换一批/缩小范围/再筛/还有别的/换些/别的导师…）即进 `handle_match_refine`，返回非 None 直接短路输出——不注册全局 DialogueMode，未确认会话不触发。
- **「换一批」**：排除集 = `excluded ∪ last_shown` → `run_confirmed_match(extra_constraints=[ADVISOR_ID EXCLUDES ...])` 重跑同画像匹配，输出"已排除已展示的 N 位候选后重新匹配："；首次无已展示批次 → 诚实说明"本轮还没有已展示的候选可排除；可以先回复「缩小范围」…"。
- **「缩小范围」**：两问状态机——Q1「你希望候选集中在哪些方向或技术上」（答 → `RESEARCH_TOPIC CONTAINS`，经 `parse_topic_answer` 分隔与去停用词）；Q2「有没有想排除的方向」（答「无」跳过 → 否则 `RESEARCH_TOPIC EXCLUDES`）→ `_run_refined` 按方向过滤重跑。答题期收到结构指令（`_refine_structural_match`：第 N 个/雷达图/招募/报告/确认交付词）→ 清 step + 释放回主流程；「取消」→ 保留已生效过滤态；`_REFINE_RESET`（恢复/重置/看全部）**优先于**取消判定 → 清全部过滤 + 重跑全量。
- **归零**：排除/过滤后无候选 → 输出 `zero_result_reason` 原文（诚实空态）+ 提示"可以回复「恢复完整结果」…或「缩小范围」…"，绝不编造。
- **一致性保证**：每次渲染后 `persist_shown_batch` 记录 `last_shown_advisor_ids`（创建 row 或保留 filters）；基础重跑（第 N 个/雷达图/套磁）也会应用 `persisted_refine_constraints`（excluded + topics），因此**换批后所有追问与二次筛选批次逐字一致**。
- **`run_confirmed_match` 扩展**：新增可选参 `extra_constraints: list[dict | HardConstraint] | None`，合并进画像 `hard_constraints` 再 `match_mentors`——matching 层 `ADVISOR_ID EXCLUDES` / `RESEARCH_TOPIC CONTAINS/EXCLUDES` 原生支持（`lexical_concept_similarity` 求值），零改动复用。

#### 11.13.2 候选详情升级（match_application.py）

- **能力差距分析 `format_gap_analysis(item, profile) -> str | None`**：
  - `direction_map.py` 新增 `DIRECTION_KNOWLEDGE`：16 规范方向 → 3~5 个公开学科入门知识点（Transformer/RLHF、贝叶斯推断、ROS、SQL 优化器…）；**只列学科常识，绝不出现教师名单/教师-方向绑定**（D1 红线）。
  - 候选方向取 `research_keywords`（官方目录方向名），回退 `_research_direction(item)`；经 `resolve_direction` 规范名命中，回退双向子串匹配。
  - 输出分支：同方向 → "建议把以下入门知识作为学习清单"；跨方向 → "建议优先补充"（引用画像其它方向）；无画像证据 → "暂无画像证据…可作参考"；方向无映射 → `None`（诚实省略该块）。
- **官方主页链接**：基本信息区追加 `官方主页：{url}`（item 有值才输出，目录条目无此字段诚实省略）。
- **六维对比条形**：`_bar(value)` = `"█"*filled + "░"*(10-filled)`，`filled = round(value/100*10)` 钳制 [0,10]；加在数值**之后**（"你的需求 80（需求映射） ████████░░"），保留既有测试子串断言；无数据不画条（绝不画 0 冒充）。

#### 11.13.3 迁移与验证

- 后端全量：**692 passed / 5 failed / 2 skipped / 2 errors**（新增 30 用例全绿：差距/主页/条形 9 + 二次筛选单测 16 + 黑盒 5；失败集与 v3.1.0 基线逐项一致，均为 Windows 环境性）。
- 二次筛选单测：换一批排除集 = 已展示批次且跨轮累积；缩小范围两问（聚焦 CONTAINS / 排除 EXCLUDES / 答「无」跳过）；取消保留过滤态；恢复清空重跑全量；归零诚实文案；答题期结构指令释放；`persist_shown_batch` 不抢占其它对话模式；`extra_constraints` 合并到画像硬约束。
- 黑盒：换一批输出新批次且旧候选不再出现、含主页链接与差距分析；缩小范围两问直通过滤结果；换批后「第 1 个」与批次一致；恢复完整结果全量回归；首次换一批诚实提示。
- 不新增 LLM 依赖、不触碰评分门禁（≥8 样本）与 D1 治理字段；「换一批/缩小范围」仅作用于已确认会话。
- 前端：`npm run type-check` 与 `npm run build` 均通过（本轮前端零改动）。

---

## 12. v4.0.0 智能体升级（任务书四任务全量交付）

> 依据《Tsing-RADAR 智能体升级执行提示词_20260820》全量落地。环境事实：docker daemon
> 未运行、无 GLM key、未安装 chroma/langchain/ultra_memory/opik → 按任务书「可替换
> 等价物」条款全部实现为**确定性等价物**，不新增第三方运行时依赖；等价物替换逐条对照见
> `docs/偏差修正记录表_v4.md`。交付目标直击用户痛点：**无关词语不再导致"无法处理"**。

### 12.1 任务1 A-1：导师评价综述级词法知识库（RAG 确定性等价物）

- **构建**（`scripts/build_mentor_knowledge.py`）：解析《清华导师评价综述_20260816.md》章节 →
  提取 姓名/院系/职称/主页/招生/四维聚合/判档/倾向/综述摘要；**剔除全部引文块**（`> 代表性` 行）；
  输出 `backend/data/knowledge/mentors.knowledge.json` + `knowledge_manifest.json`
  （来源 + SHA256 + 口径声明），构建时自检 manifest 一致。
- **查询**（`mentor_knowledge.py`）：`query_mentor_knowledge(name)` 姓名精确/子串匹配（确定性，
  无向量库）；`render_mentor_knowledge` 输出知识块，头部固定声明
  「公开存档匿名主观评价聚合，仅作参考，不构成对导师能力的客观评判」；未收录 →
  「该信息暂未收录：暂无「{name}」的公开评价综述，建议通过官方邮箱联系导师确认。」
- **意图路由**（`dialogue_intent.py`）：`MENTOR_KNOWLEDGE` 意图——前缀（请问/想了解/了解下/
  帮我看看/查一下/把/说说/听说…）× 姓名（百家姓门控 + 2~4 字 + 老师/教授/导师 后缀）× 咨询词
  （怎么样/评价/邮箱/电话/主页/缺点/传闻/研究什么…）；防误伤：无姓名或非咨询句 → None 放行。
- **治理边界**：知识库只作咨询参考，**绝不混入雷达/匹配客观管线**；popularity/sector 仍禁止；
  回复带声明；无引文、可溯源（SHA256）。

### 12.2 任务1 A-2：长期记忆（Ultra-Memory 确定性等价物）

- **表**：`user_memories`（见 §5.4 表 19；迁移 0014）。
- **写入门禁**：`memory_service.remember_confirmed_portrait`——白名单六维 + 硬性条件 +
  确认门标记，**仅确认门通过后**写入（`answer_session` 确认分支 / `confirm_profile`）；
  幂等覆盖，重新确认即更新。
- **召回注入**：`format_memory_summary` 生成事实片段（无框架词）→ 表达层
  `FactPack.memory_summary` 注入（仅访谈回复；确认门/匹配结果不增强——红线不变）。
- **隐私**：`list_memories` / `clear_memories` 供用户查看与清除。

### 12.3 任务1 A-3：提示词版本化

- `backend/app/services/prompts/`：`system_prompt_v1.txt` / `rewrite_template_v1.txt` /
  `prompt_versions.json`（版本清单）。
- `load_prompt_template(name, fallback)`：版本清单一致才加载文件；文件缺失/损坏/清单不一致/
  空文本 → 回退代码内嵌 v1 兜底（fail-closed，与 v3.1.x 逐字一致）。
- 版本对比记录写入 `docs/评估与提示词优化记录_v4.md`。

### 12.4 任务1 A-4：离线评估闭环（Opik 确定性等价物）

- `scripts/eval_offline.py` + `eval_cases_v4.json`：**60 例对抗样本**——访谈各阶段/确认门/
  匹配后/招募/雷达/记忆/**红线对抗**（诱导编造导师信息、篡改 tolerance、他人事务索取、编造名单）；
  组分布：redline 17 / offtopic 10 / interview 7 / confirmation 4 / matched 5 / recruitment 4 /
  mentor_knowledge 6 / memory 2 / degradation 5。
- **会话驱动**（与网关协议一致）：每次请求携带**完整累积历史**（`sync_user_transcript`
  `user_messages[persisted_user_turns:]` 语义）；身份预热直连 DB 建 `ExternalIdentity` 映射
  （与 `resolve_qxd_principal` 同一 fingerprint），不 HTTP probe（避免污染多轮会话）。
- **确定性指标**：事实保真（关键数字逐字）、红线违规率（=0，否则非零退出）、降级正确率、
  跑题处理正确率；报告 `docs/评估与提示词优化记录_v4.md`。
- docker daemon 不可用 → Opik 平台不落地（替换理由记录于偏差修正记录表）。

### 12.5 任务1 阶段B：确定性工具注册表

- `tools_registry.py`：3 只读工具 `query_mentor_knowledge` / `get_recruitments` /
  `recall_memory`；`TOOL_SCHEMAS` 与 OpenAI function-calling 对齐（type=function /
  name / description / parameters JSON Schema）。
- **本期服务端确定性路由**：chat.py 状态机决定调用与参数——MENTOR_KNOWLEDGE 意图 →
  `query_mentor_knowledge`（姓名由意图层提取）；RECRUITMENT 匹配态分支 → `get_recruitments`
  （复用已确认画像相关度排序）；记忆注入同源 `format_memory_summary`。**LLM 不自主调用**
  （匹配/确认门红线逐字保留）。
- **fail-closed**：未知工具/未知参数/缺必填/类型错/越界/执行异常 → 确定性错误文本，
  不抛异常、不吞消息、不编造。

### 12.6 越界话题优雅处理（用户痛点直击）

- `off_topic.py` 确定性词法守卫，三处接入：
  1. **访谈防吸收**（`interview.answer_session`）：研究兴趣无方向/声明词且非问候/不确定 →
     不写画像、温和重问；选择题无维度词且非不确定 → 重问（不再推进 undecided）；硬条件无锚词
     → 重问。
  2. **他人事务/篡改/编造**（`_is_other_person_request` + `_FABRICATION_WORDS`）：
     姓氏锚定正则 `[百家姓][\u4e00-\u9fa5]{0,3}?(老师|教授|导师|同学)` × 索取信息词
     （邮箱/电话/主页/招生/名额/传闻/缺点/改成/改为…）→ 跑题重问；夹带方向词也不放行；
     「把我的研究兴趣改成机器学习」等本人自述不误伤。
  3. **匹配态兜底**（`chat.py`）：`_POST_CONFIRM_OUTCOME_STATUSES`（matched / no_match /
     no_published_data）统一覆盖——跑题 → 能力引导（不再静默重跑/复读空态）；致谢 →
     优雅回应。
- **导师信息咨询路由**：邮箱/电话/主页/缺点/传闻/研究内容等咨询词 → 知识库块（§12.1）。

### 12.7 任务2 雷达文本化（承接 v3.1.3）

- `render_radar_bars` 独立条形渲染 + 形态选择配置；QXD 默认文本版（内联条形），附件版 SVG/PDF
  同数据源；客观与主观严格分离（红线）。

### 12.8 任务3 招募增强

- 双源实时查询（静态目录 + 数据库投稿，verified/published/未下架/未过期）已交付；
- **FactPack 招募摘要**：`InterviewFactPack.recruitment_summary` + `_validate_expression`
  **逐字校验**（截止/名额/申请方式等 token 必须逐字出现，守住「不增强」红线）；
- **确认后一次性主动触达**：确认门通过且存在画像相关开放招募（relevance>0）→ 追加一行
  「顺带一提：X 组正在招科研助理（截止…），回复「招募信息」可查看」；仅确认消息触发一次，
  无则静默。

### 12.9 迁移与验证

- 后端全量：**787 passed / 4 failed / 2 skipped / 2 errors**（新增 40 用例全绿：越界守卫 +
  知识库 + 记忆 + 工具注册表 + prompts + 招募逐字校验/主动触达；剩余 4 failed + 2 errors 为
  Windows 环境性基线——字体路径/归档字节确定性/symlink 特权/POSIX 权限，见 README 已知问题；
  本版本顺带修复陈旧迁移链断言，基线失败由 5 项降为 4 项）。
- 离线评估：**60/60 通过、红线违规 0/17、事实保真 5/5**。
- 黑盒：导师咨询命中知识库块（判档/声明/主页）；张三丰未收录诚实拒答；他人事务温和重问；
  匹配态跑题能力引导；致谢优雅回应。
- 前端：`npm run type-check` + `npm run build` 通过（本轮前端零改动）。
- 文档：`CHANGELOG.md`、`README.md`、`docs/缺陷修复清单_v4.md`、`docs/偏差修正记录表_v4.md`、
  `docs/评估与提示词优化记录_v4.md`。
