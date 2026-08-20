# Tsing-RADAR 变更日志

---

## v4.0.0（2026-08-20）

> 按《Tsing-RADAR 智能体升级执行提示词》全量升级：任务1 四大能力（AI 语言增强：
> RAG→综述级词法知识库 / 长期记忆→自有 user_memories 表 / 提示词版本化 / 离线评估闭环
> 60 例）+ 阶段B 工具注册表、任务2 雷达文本化承接、任务3 招募增强（FactPack 逐字校验 +
> 确认后一次性主动触达）、任务4 收尾文档与打包。**用户痛点直击**：无关词语不再被吞进画像
> 或静默复读匹配——越界话题（天气/笑话/他人事务/编造请求/篡改指令）一律温和重问或能力引导。

### 新增

- **导师公开评价综述级词法知识库**（任务1 A-1 确定性等价物，`build_mentor_knowledge.py` +
  `mentor_knowledge.py` + `backend/data/knowledge/`）：解析综述章节 → 姓名/院系/职称/主页/招生/
  四维聚合/判档/倾向/综述摘要，**剔除全部原始引文块**；`knowledge_manifest.json` 登记来源 +
  SHA256 + 口径声明（可溯源）；姓名精确/子串匹配，未收录诚实拒答；回复带
  「公开存档匿名主观评价聚合，仅作参考，不构成对导师能力的客观评判」声明。
  **只作咨询参考，绝不混入雷达/匹配客观管线**；popularity/sector 仍禁止。
- **长期记忆确定性等价物**（任务1 A-2，`user_memories` 表 + `memory_service.py`）：
  白名单写入——仅已确认画像六维 + 硬性条件 + 确认门标记（未确认猜测绝不写）；跨会话召回注入
  表达层 FactPack（仅访谈回复；确认门/匹配结果不增强）；隐私查看 `list_memories` / 清除
  `clear_memories`；迁移 `0014_user_memories.py`。
- **提示词版本化**（任务1 A-3，`backend/app/services/prompts/`）：`system_prompt_v1.txt` /
  `rewrite_template_v1.txt` + `prompt_versions.json` 版本清单；`load_prompt_template` 运行期加载，
  版本不一致/文件缺失/损坏 → 回退内嵌 v1 兜底（fail-closed，行为与 v3.1.x 逐字一致）。
- **离线评估闭环**（任务1 A-4，`scripts/eval_offline.py` + `eval_cases_v4.json` 60 例）：
  对抗样本覆盖访谈各阶段/确认门/匹配后/招募/雷达/记忆/**红线对抗**（诱导编造导师信息、篡改
  tolerance、他人事务索取、编造名单）；确定性指标——事实保真（关键数字逐字）、红线违规率（=0）、
  跑题处理正确率；报告写入 `docs/评估与提示词优化记录_v4.md`（含 A-3 提示词版本记录与阶段B
  工具注册表记录）。docker daemon 不可用 → Opik 平台不落地，记录替换理由。
- **确定性工具注册表**（任务1 阶段B，`tools_registry.py`）：3 只读工具
  `query_mentor_knowledge` / `get_recruitments` / `recall_memory`，OpenAI function-calling
  对齐 Schema；**本期服务端确定性路由**（chat.py 状态机决定调用与参数，LLM 不自主调用——
  匹配/确认门红线逐字保留）；fail-closed：未知工具/参数非法/执行异常 → 确定性错误文本。
  chat.py 的 MENTOR_KNOWLEDGE / RECRUITMENT 分支已改经注册表分发，行为与既有 handler 逐字一致。
- **越界话题优雅处理**（用户痛点直击，`off_topic.py` 词法守卫）：
  - 研究兴趣文本题：天气/笑话/点外卖等完全无关 → **不写入画像、温和重问**；
  - 选择题：无维度关键词且无不确定词 → 重问，不再推进为 undecided；
  - 硬条件题：无约束锚词 → 重问而非生成 0 置信 draft；
  - **他人事务**（把张三同学的联系方式给我 / 说说李琦老师的缺点 / 篡改指令把 tolerance 改成 95）：
    姓氏锚定正则 + 信息索取词先行拦截（夹带方向词也不放行）；
  - **编造请求**（编一个推荐名单，不用真实数据）：拦截重问，绝不产出编造数据；
  - 匹配态兜底：跑题消息 → 能力引导（不再静默重跑匹配）；空结果（no_match / no_published_data）
    同样适用——诚实空态保留但不再刷屏；致谢 → 「不客气～有需要可以随时继续追问」。
- **导师信息咨询路由**：邮箱/电话/联系方式/主页/缺点/传闻/研究内容等咨询词 + 新前缀
  把/说说/听说 → 综述级知识库块（确定性，不经 LLM）；未收录诚实拒答并建议官方邮箱确认。
- **招募增强**（任务3 缺口补齐，`recruitment_public.py` / `chat_expression.py`）：
  FactPack 增 `recruitment_summary` 段 + 表达层**逐字校验**（招募字段 token 必须逐字出现，
  守住「不增强」红线）；确认门通过后**一次性主动触达**——存在画像相关开放招募时追加一行
  「顺带一提：X 组正在招科研助理（截止…），回复「招募信息」可查看」，仅触发一次不刷屏；
  无则静默。
- **缺陷修复**（四段式清单见 `docs/缺陷修复清单_v4.md`）：导师信息咨询被吸收进画像、他人事务
  被当研究兴趣、编造/篡改请求未拒绝、匹配态空数据复读、评估脚本多轮会话失效（会话驱动改为
  完整历史累积）、迁移链断言陈旧（0012→0014，消除 1 项基线失败）。

### 验证

- 后端全量：**787 passed / 4 failed / 2 skipped / 2 errors**（新增 40 用例全绿：越界守卫 6 +
  知识库 12 + 记忆 8 + 工具注册表 16 + prompts 7 中新增部分 + 招募逐字校验/主动触达；
  剩余 4 failed + 2 errors 为 Windows 环境性基线（字体路径/归档字节确定性/symlink 特权/
  POSIX 权限），见 README「已知问题」与缺陷修复清单第二节）。
- 离线评估：**60/60 用例通过，红线违规率 0/17，事实保真 5/5**（`scripts/eval_offline.py` 复跑）。
- 黑盒：导师信息咨询命中知识库块（含判档/声明）；张三丰未收录诚实拒答；把张三同学的联系方式
  触发温和重问；匹配态跑题给能力引导；确认后致谢优雅回应。
- 前端：`npm run type-check` + `npm run build` 通过（本轮前端无改动）。

### 等价物替换理由表（任务书 → 交付）

见 `docs/偏差修正记录表_v4.md`（RAG→词法知识库、Ultra-Memory→user_memories 表、Opik→离线评估、
工具注册表本期确定性路由、无 docker/无 key 前提逐条记录）。

---

## v3.1.7（2026-08-20）

> 竞品蒸馏落地（清研向导实测三缺口补齐）：匹配后**二次筛选闭环**（换一批 / 缩小范围 / 恢复完整结果）+ **能力差距分析**（需要补充的知识或技能）+ **候选官方主页链接**，并把六维对比升级为 10 格条形可视化——量化优势继续打透。

### 新增

- **匹配结果二次筛选**（`match_refine.py`，新服务 + `chat.py` recommend_ready 接线）：
  - 「换一批」：把已展示候选并入排除集（`ADVISOR_ID EXCLUDES` 硬约束）重跑同画像匹配；排除集跨轮累积，每批候选经 `persist_shown_batch` 记录到 `dialogue_sessions.state`，保证换一批后「第 N 个 / 雷达图 / 套磁」追问与二次筛选批次一致。
  - 「缩小范围」：两问状态机（Q1 聚焦方向 → `RESEARCH_TOPIC CONTAINS`；Q2 排除方向 → `RESEARCH_TOPIC EXCLUDES`，答「无」跳过）→ 按方向过滤重跑；答题期收到「第 N 个 / 雷达图 / 招募 / 生成报告」等结构指令时放弃未答完的问题释放回主流程（`_refine_structural_match`），「取消」保留已生效筛选条件。
  - 「恢复完整结果」：清空排除集与方向过滤后重跑全量；归零走 `zero_result_reason` 原文 + 提示恢复，绝不编造；首次直接「换一批」（无已展示批次）诚实说明无法排除。
  - `run_confirmed_match` 新增可选参 `extra_constraints`（合并进画像 hard_constraints，matching 层 `ADVISOR_ID/RESEARCH_TOPIC` 硬过滤原生复用，零改动）；`DialogueMode` 新增 `MATCH_REFINE`（仅 recommend_ready 上下文生效，不注册全局对话模式）；匹配结果引导文案追加「换一批 / 缩小范围 / 恢复完整结果」。
- **能力差距分析**（`match_application.format_gap_analysis` + `direction_map.DIRECTION_KNOWLEDGE`）：16 规范方向 → 3~5 个公开学科入门知识点（**只列学科常识，绝不出现教师名单**，D1 红线）；候选方向经 `research_keywords`/研究方向文本归一化匹配，与学生画像兴趣做词面比对，输出「已具备/需要补充/学习清单」；无画像证据诚实标注，方向无映射省略该块。
- **候选官方主页链接**（`format_match_item`）：基本信息区追加 `官方主页：{url}`（item 有值才输出，目录条目无此字段诚实省略）。
- **六维对比条形可视化**（`match_application._dimension_compare_block`）：每侧数值后附 10 格 `█/░` 条形（与 v3.1.5 文本版雷达同风格；无数据不画条，绝不画 0 冒充）。

### 验证

- 后端全量：**692 passed / 5 failed / 2 skipped / 2 errors**（新增 30 用例全绿：差距分析 5 + 主页/条形 4 + 二次筛选单测 16 + 黑盒 5；失败集与 v3.1.0 基线逐项一致，均为 Windows 环境性）。
- 二次筛选单测：换一批排除集 = 已展示批次且跨轮累积；缩小范围两问（聚焦 CONTAINS / 排除 EXCLUDES / 答「无」跳过）；取消保留过滤态；恢复清空重跑全量；归零诚实文案；答题期结构指令释放；`persist_shown_batch` 不抢占其它对话模式；`extra_constraints` 合并到画像硬约束。
- 黑盒：`换一批` 输出新批次且旧候选不再出现、含主页链接与差距分析；`缩小范围` 两问直通过滤结果；换一批后「第 1 个」与批次一致；`恢复完整结果` 全量回归；首次「换一批」诚实提示。
- 前端：`npm run type-check` + `npm run build` 通过（本轮前端无改动）。

---

## v3.1.6（2026-08-20）

> 对话闭环：把雷达 / 契合度构成分解 / 科研风格速测 / 方向地图 / 套磁邮件串成**有上下文记忆、可追问、可回填**的对话旅程——匹配后可继续「第 N 个」追问，探索结果能真正写回画像。

### 新增

- **匹配后「第 N 个」候选追问**（`chat.py` / `match_application.py`）：
  - 分发层短路：会话已确认（或同请求前序消息刚完成画像确认）时，`第 N 个` 优先指代**匹配候选**而非招募列表序号（`_ordinal_follows_match_results` + 复用 `recruitment_dialogue._parse_ordinal`）；未确认会话的招募序号行为不变。
  - 三种追问全通：`第 N 个` → 单候选详情（`format_match_item` 从 `format_match_outcome` 逐字抽出，两处共用同一渲染）；`第 N 个的雷达图` → 按序号签发 SVG 附件（`_select_radar_item` 增 ordinal 定位，越界/无评分走诚实空态并点名目标）；`第 N 个的套磁邮件` → 把候选名注入 `handle_consult_email` 定向生成。序号越界诚实提示候选总数。
  - 匹配结果末尾自动追加"下一步引导"（详情 / 雷达 / 套磁三行；直接「雷达图」行仅在有已审核评分时提示）。
- **科研风格速测「确认」回填 research_mode**（`research_style.py` / `interview.py`）：答完 4 题后保留 pending 态（不再直接清模式），回复「确认」经 `upsert_portrait_field` 把偏好形态写入画像研究方式并清模式；「取消」放弃、「重测」重来、导航词（匹配/招募/方向地图等）清模式放行走主流程，其它消息保持 pending 提醒——防止"匹配导师"等短词掉进未确认访谈被误当答案。
- **方向地图选方向 → 回填 research_interests + 引导**（`direction_map.py`）：地图从"单轮静态输出"升级为闭环，回复方向名（别名或完整规范名）→ 规范化 → 合并去重写入画像研究兴趣（含既有值、上限 8、自动补兴趣陈述）→ 引导「确认画像」/「招募」；未命中方向只放行一次不吞访谈自述，取消即退出。治理边界不变：只回填方向本身，不涉及教师名单。
- **`upsert_portrait_field`**（`interview.py`）：对话端口专用画像单字段写回——无版本冲突检查、内部自增版本、`research_interests` 合并去重；已确认画像被改动后状态回落 `awaiting_confirmation`（与 `patch_profile` 既有语义一致，需重新确认）。
- **对话释放同步守卫**（`chat.py`）：对话模式（风格速测/方向地图等）释放放行后，访谈增量同步只喂最新一条消息——已被对话模式消费的轮次不再重放给访谈，避免"测测我/1/2"被误当成访谈答案。

### 验证

- 后端全量：**662 passed / 5 failed / 2 skipped / 2 errors**（新增 17 用例全绿：画像回填 3 + 单候选渲染 1 + 风格 pending 5 + 方向闭环 4 + 黑盒序号追问 4；失败集与 v3.1.0 基线逐项一致，均为 Windows 环境性）。
- 序号追问黑盒：`第2个` 单候选详情含第二位姓名/院系/契合度；`雷达图 第2个` 签发第二位 SVG；`第2个的套磁邮件` 以"给测试导师二写一封套磁邮件"注入并输出初稿；`第9个` 诚实越界无附件。
- 风格/方向回填：确认后 DB 画像 `research_mode`/`research_interests` 正确写入、模式清除；取消不写；别名 miss 诚实提示不编造；已确认画像回填后回落待确认。
- 前端：`npm run type-check` + `npm run build` 通过（本轮前端无改动）。

---

## v3.1.5（2026-08-20）

> 雷达改边缘线图勾连（四端口无填充）+ 特色「契合度构成分解」：不仅报"契合度 XX 分"，还倒推为什么是这个分数。

### 新增

- **契合度构成分解**（`match_application.py`）：新增 `format_fit_breakdown`，把排序流水线已算好的 `score_breakdown`（score×权重×置信度）倒推成可读块——`▲ 拉高 / ▼ 拉低 / · 中位`（按该维得分与 fit_score 差 ≥±3 分判定）+ 权重 + 得分；画像无证据的维度诚实标注`未计入（画像无该维度证据，确认后生效）`，绝不用基准值冒充；标题声明"由排序分数倒推，与保守排序分同一口径，非新增评分"。接入 `format_match_outcome` 候选头部之后，breakdown 缺失/为空时省略该块（旧数据与既有流程零破坏）。这是对竞品"不评价能力高低、回避量化"定位的差异化回答：**量化 + 可解释 + 证据链**。

### 变更

- **雷达图 → 边缘线图勾连（无颜色填充）**，四端口同步：
  - SVG（`radar_chart.render_radar_svg`）：数据多边形 `fill-opacity="0.45"` 填充 → `fill="none"` 纯描边，并新增**顶点勾连点** `<circle r="3">`；图例同步无填充；删除 `ADVISOR_TRAIT_FILL_OPACITY` 常量。
  - 文本版（`_render_text_polygon`）：删除多边形内部 `█` 填充（`_point_in_poly` 移除），只保留边缘勾连；逐维数值条形不受影响。
  - PDF（`render_radar_drawing`）：reportlab 数据多边形 `fillColor=None`。
  - 前端（`useRadarOption.ts`）：删除 ECharts `areaStyle` 与 `RadarSeries.areaColor` 字段及四组配色常量；`variables.scss` 清理填充色变量；`splitArea` 网格背景保留。

### 验证

- 后端全量：**645 passed / 5 failed / 2 skipped / 2 errors**（新增 7 用例全绿：雷达线图 1 + 构成分解单测 4 + 黑盒 2；失败集与 v3.1.0 基线逐项一致，均为 Windows 环境性）。
- 雷达线图契约：SVG `fill="none"` 计数 7（网格 5 + 数据 1 + 图例 1）、无 `fill-opacity`、顶点勾连点 4 个；文本版满值多边形边缘 48 格 < 80 上界（内部填充会 >120）；reportlab 多边形 `fillColor is None`；黑盒附件/文本双路径仍正常。
- 构成分解：四类行、阈值边界（±3 含边界）、确定性（同输入同输出）、缺失 breakdown → None、未知目标回退原始键；黑盒验证对话端口输出构成块、无 breakdown 时诚实省略。
- 前端：`npm run type-check` + `npm run build` 通过。

---

## v3.1.4（2026-08-20）

> 竞品优势内化（清研向导实测）：科研风格速测（4 题确定性分类）、研究方向地图（不输出教师名单）、画像确认增强（匹配重点 + 未明确项引导）。

### 新增

- **科研风格速测**（`research_style.py`，新）：学习竞品"清研向导"16 题 LLM 风格测试，做成我们的轻量确定性版本——4 题（研究范围 / 推进方式 / 理论 vs 工程 / 成果偏好），9 种"形态 × 驱动"核心风格规则表分类（问题溯源型 / 理论建构型 / 落地攻坚型 / 方法工程型 / 数据驱动型 / 实证归纳型 等），同答案同结果、可测试可复现。诚实红线与竞品措辞对齐：只描述当前更偏好的科研方式，**不判断是否适合科研、不评价能力高低**；结果不回填任何六维导师评分，仅提示可选回填画像 `research_mode`（theory/engineering/mixed，"「确认」后生效"）；多轮状态走 `dialogue_sessions`（mode=research_style），支持「取消」退出、非法答案同题重试，完成后自动清除状态。
- **研究方向地图**（`direction_map.py`，新）：帮"说不清兴趣"的用户把模糊诉求变成可选方向词——16 个公开学科方向（大模型/NLP/视觉/ML/RL/机器人/系统/网络/数据库/芯片/通信/理论计算/材料化学生物/生物信息/新能源/控制优化仿真），每条含一句话说明 + 示例关键词；34 项别名归一（NLP↔自然语言处理、LLM↔大模型、自动驾驶↔机器人 等），与招募筛选口径打通。**治理边界：只输出学科方向本身，刻意不输出参考教师名单**（教师-方向绑定属非公开数据治理范围，知识库无证据时不编造，D1 红线）。
- **画像确认增强**（`interview.py` `_summary`）：确认画像摘要新增两行——"**匹配时将重点考虑**"（研究方向/研究方式/生涯方向/指导偏好/硬性条件，无信息时诚实提示"暂无已确认信息，先匹配会较宽泛"）与"**尚未明确（可选补充）**"（待确认硬性条件 + 未明确的 research_mode/career_orientation 引导，"无"时诚实写"无"），让用户明确知道匹配会用什么、还缺什么。"确认画像"口令与既有流程完全兼容。
- **意图分类扩展**（`dialogue_intent.py`）：新增 `RESEARCH_STYLE`（科研风格/风格测试/测测我/我适合做什么方向/了解自己 等）与 `DIRECTION_MAP`（有哪些方向/方向地图/方向怎么选 等）两个模式；方向地图触发词刻意用**完整问句结构**，不引入裸词"方向"，避免拦截访谈自述（"我研究方向是自然语言处理"仍归访谈）；"测测我"（自我认知）优先于"什么方向"（方向地图）。

### 验证

- 后端全量：**638 passed / 5 failed / 2 skipped / 2 errors**（新增 16 用例全绿；失败集与 v3.1.0 基线逐项一致，均为 Windows 环境性）。
- 科研风格速测：10 用例覆盖确定性（同答案同结果）、3 种 mode 映射、序号精确匹配（"11" 不误中 "1"）、4 轮全流程、取消退出、非法重试不推进；黑盒 3 用例（多轮直出 + 取消 + 方向地图单轮）验证不触碰访谈状态机（`QuestionnaireSession` 0 记录）。
- 方向地图：16 方向全列出、方向名唯一、渲染不含"参考教师"、别名命中与未收录返回 None（不语义推断）。

---

## v3.1.3（2026-08-20）

> 正常人说法实测 + 仅对话端口雷达图：意图触发词按真人口语实测扩充 20 项、简历首轮引导去重、评分文件损坏诚实降级、雷达图文本字符版直出对话。

### 新增

- **文本版雷达图（仅对话端口直出）**（`radar_chart.py` ↔ `chat.py`）：清小搭纯对话端口没有附件能力，新增 `render_radar_text` 把客观四维证据渲染为字符雷达图——多边形骨架（Bresenham 线 + 射线法填充）+ 每维 20 格数值条形（█/░）+ 样本来源；与附件版同一数据来源（`public_score_bundles` 门控），任何分支（附件未启用 / 交付未就绪）都诚实降级为文本版并保留"客观指标与匿名主观评价严格分离，本图不含学生评价"声明，绝不静默丢图。
- **意图分类真人口语扩充**（`dialogue_intent.py`）：按 51 例正常人说法扫描实测补齐 20 处漏匹配——定向优化新增"润色下/优化下/提高/改进/看看简历"等；从零生成新增"帮我写简历/做一份/整一份"等；简历粘贴启发式（≥2 个完整字段锚点 → 简历润色）；招募新增"招人吗/在招/急招/实习机会"等；FAQ 新增"咋弄/怎么办/干嘛的/有什么用"等；四象限、套磁补充口语变体。全部变体均带边界护栏（"实习经历/性能优化/方向是热门"等访谈答案不误触发），非路由语句仍归访谈。
- **评分文件损坏诚实降级**（`mentor_score_governance.py`）：`load_score_dataset` 捕获 `ValidationError` → 日志记录后返回 None（诚实空态），不再让整条雷达链路 500。

### 修复

- **简历首轮引导重复**（`resume_dialogue.py`）：从零生成引导文案与 `FIELD_SEQUENCE[0]` 重复说"好的，我们从零开始写简历…"；第一步改为只问"你的姓名是？"，消息更短、更像真人引导。
- **FAQ 顺序拦截**（`consultation.py`）："简历" FAQ 条目误放"怎么投递"之前会拦截"怎么投递简历"，移到"投递流程"之后；雷达图 FAQ 主题改为"雷达图"以匹配"是啥/干嘛的/有什么用"。
- **测试环境隔离**（`conftest.py`）：测试进程强制清空 `MENTOR_SCORE_DATA_FILE`/`MENTOR_SCORE_DATA_EXPECTED_SHA256`，防止本机 .env 旧 schema 评分文件污染测试。

### 验证

- 后端全量：**622 passed / 5 failed / 2 skipped / 2 errors**（新增 9 用例全绿；失败集与 v3.1.0 基线逐项一致，均为 Windows 环境性）。
- 意图层：51 例真人说法扫描 → 50 全对 + 1 个已记录边界（"找大模型相关的"依赖上下文延续，不为此引入访谈误伤）。
- 雷达图文本版：确定性、全 0 → 中心点 + 空条（诚实）、全 100 → 完美菱形、轴序与客观四维键对齐；黑盒测试覆盖附件启用（SVG 附件）与禁用（文本直出）双路径。

---

## v3.1.2（2026-08-19）

> 招募推荐闭环 + 简历体检：筛选偏好跨轮记忆、岗位详情追问、岗位要求联动定向润色。

### 新增

- **招募偏好跨轮记忆**（`recruitment_dialogue.py`）：用户明确说过的筛选条件（院系/类型/急招/方向）写入 `dialogue_sessions`（mode=recruitment_query）；之后宽泛查询（"还有吗/随便看看"）自动沿用并说明"我沿用你之前提到的筛选条件…"，新条件整体替换旧记忆。
- **岗位详情追问**：推荐列表后回复「第 1 个 / 第一个 / 第 3 个怎么样」→ 单条完整详情（发布方·院系 / 类型|截止 / **距截止天数** / 急招 / 核心要求 / 投递说明 / 推荐理由）+ 定向优化引导；序号解析支持阿拉伯与中文数字（第一…第十、第十二）；序号越界诚实提示；意图分类新增"岗位/招聘"触发词与「第 N 个」指代识别（`dialogue_intent.py`）。
- **岗位要求联动定向优化**（`resume_dialogue.py` ↔ `recruitment_dialogue.py`）：`resolve_recruitment_target` 按 序号（与 digest 同口径排序）→ recruit_id → 标题子串 把目标解析为公开岗位；润色提示词自动附加该岗位公开核心要求（"供你匹配表述，不得虚构经历"），无 LLM/解析失败按普通目标名处理。
- **简历完整性体检**（`_finalize_build`）：生成后自动提示关键缺失——无科研/项目经历、无联系方式、无教育背景，均为诚实建议（"建议补充…"），不虚构内容。

### 修复

- `resume_dialogue.py` 顶部 `import json` 在早期清理时被误删：无 LLM 凭据时 `_llm_polish`/`_prefill_llm` 提前短路所以测试未暴露，配置凭据后 `json.loads` 抛 NameError；本次补回（新测试注入凭据后覆盖此路径）。

### 验证

- 后端全量：**616 passed / 5 failed / 2 skipped / 2 errors**（新增 8 用例全绿；失败集与 v3.1.0 基线逐项一致，均为 Windows 环境性）。
- 简历/招募专项：36 用例全绿（新增 序号解析与详情判定 / 第 N 个详情 / 序号越界诚实 / 条件记忆沿用 / 新条件替换 / 岗位解析 / 体检提示 / 岗位要求进提示词 8 项）。

---

## v3.1.1（2026-08-19）

> 对话智商快进：简历智能预填 + 招募方向同义归一化，宽泛（"大方"）问题有明确引导。

### 新增

- **简历智能预填**（`resume_dialogue.py`）：触发消息或任一采集轮一次性给出的信息由 LLM（fail-closed，≥2 非空字段才采用）或确定性锚点（姓名/院系/教育/项目/荣誉/补充 6 类，按句归类）抽取为字段，只问缺失项——"我叫张三，计算机系，大三…"这类密集输入从 6 轮压缩到 1 轮；推进逻辑改为"下一个未答字段"，与空答案跳过语义兼容。
- **招募方向别名归一化**（`recruitment_dialogue.py`）：`DIRECTION_ALIASES` 双向映射（NLP ↔ 自然语言处理、LLM ↔ 大模型、RL ↔ 强化学习、AI ↔ 人工智能 等 14 组），解析、筛选、画像兴趣匹配、相关度排序统一走同义匹配；纯英文缩写按词边界匹配（"AI" 不误命中 training）；兴趣命中输出归一化规范词。
- **宽泛问题引导**：招募无筛选条件时，有画像按研究兴趣排序推荐并给出院系/类型/方向筛选引导，无画像展示最新在招概览后引导；简历采集轮"随便/都行/不知道"等宽泛回答留空跳过不追问；从零生成引导文案明确支持"一次说完所有信息"。

### 验证

- 后端全量：**608 passed / 5 failed / 2 skipped / 2 errors**（新增 9 用例全绿；失败集与 v3.1.0 基线逐项一致，均为 Windows 环境性）。
- 简历/招募专项：28 用例全绿（新增 预填触发 / 采集轮补缺 / 宽泛回答跳过 / 引导文案 / 方向归一化 / 双向同义匹配 / AI 词边界 / 有画像引导 / 无画像引导 / 空数据诚实空态 9 项）。

---

## v3.1.0（2026-08-19）

> 分支 `feature/v25-dialogue`：清小搭纯对话入口 v2.5 升级——简历对话模块、招募对话增强、对话智能度（意图分类/口语-维度映射/隐式关注识别）、纯对话文本化转译、套磁邮件与 FAQ 咨询、匹配输出 v2.5 格式。

### 新增

- **对话智能基座**（`dialogue_intent.py` + `dialogue_state.py` + 迁移 0013 `dialogue_sessions`）：意图分类优先级 定向 > 优化 > 从零 > 招募 > 四象限 > 套磁 > FAQ；口语→专业维度映射词典；隐式意图识别（窗口 4 轮 ≥2 命中）；跨轮状态持久化（状态写入即提交，与 interview.py 惯例一致）。
- **简历对话模块**（`resume_dialogue.py`）：从零生成（6 字段分步采集 → 确定性 Markdown 简历，终局清状态）；优化已有（粘贴 → LLM 润色，无凭据/失败完全降级确定性整理）；定向优化（目标导师/岗位解析 + 润色权重调整）；PDF 交付诚实降级——平台短时公开转存仅支持匹配报告（`issue_delivery_grant` 安全策略），聊天内不尝试越权签发，引导 Web 端简历中心。
- **招募对话增强**（`recruitment_dialogue.py`）：自然语言筛选（院系别名/类型/急招/方向关键词）；个性化推荐指数（★ 上限 5）；v2.5 摘要格式（标题/类型|截止/核心要求 90 字摘要/投递说明/推荐理由）；无重合诚实空态；静态招募记录补全 `dept`/`publisher_name`。
- **纯对话文本化转译**（`scatter_dialogue.py`）：四象限文本分类（已审核客观证据 项目广度 × 主题广度，>60 热；体制属性/热门度属治理剥离字段不公开，门控未开诚实空态）。
- **咨询与 FAQ**（`consultation.py`）：套磁邮件确定性模板 + LLM 增强（失败降级，联系方式以官网为准）；平台机制 FAQ 确定性答案；导师个体情况（组会/延毕/名额/风评）无收录数据诚实"暂未收录"提示。
- **匹配输出 v2.5 格式**（`match_application.py`）：契合度分数头 + 基本信息 + 核心研究方向 + 六维度分项对比表（用户侧为画像需求映射 + 隐式关注，导师侧 ≥8 样本匿名评价，无数据诚实空态）；`format_match_outcome` 签名向后兼容。
- **chat.py 分发集成**：探针请求（max_tokens:1）绝不进入对话模式；活动模式优先于新意图分类（防止简历字段答案被劫持）；对话模式绕过访谈状态机并返回 `stage="dialogue"` reasoning 档位。

### 变更

- 简历意图触发词扩展（"写一份简历"/"从零写"/"润色"/"针对"等自然口语），补充 2 处关键词缺口。
- `_NOT_COLLECTED_TEMPLATE` 措辞统一为"暂未收录"（对齐 v2.5 规格）。
- `dialogue_state_store` 状态写入/清除后立即提交（修复跨请求状态丢失）。

### 验证

- 后端全量：**598 passed / 5 failed / 2 skipped / 2 errors**（失败集与 v3.0 基线完全一致，均为 Windows 环境性：迁移 L3、CJK 字体、LLM secret 权限/symlink）。
- v2.5 专项：`test_dialogue_intent.py`（7）/ `test_resume_dialogue.py`（12）/ `test_recruitment_dialogue.py`（7）/ `test_scatter_dialogue.py`（5）/ `test_consultation.py`（8）/ `test_match_application_format.py`（7）/ `test_qxd_contract.py` 对话模式黑盒 6 用例——合计 52 个新用例，7 个文件联合运行 93 用例全绿。

---

## v3.0.0（2026-08-19）

> 整合分支 `integration/final-20260819`：导师服务 Web 前端 + 平台接入（PA）+ 客观雷达数据 + 访谈表达层增强，两侧历史完整合并（merge，非 squash）。

### 新增

- **导师服务门户**：清华邮箱验证码登录、校园卡核验（脱敏卡号）、治理档案认领、字段级编辑（进管理员审批）、意向中心（站内投递收件箱）、导师侧招募管理、隐私控制与下架申请。前端 `/mentor/*` 7 个页面 + `mentor/` 组件目录。
- **导师评分社区**：六维主观评分（学术敏锐度/人脉/指导意愿/包容度/经费/产出），服务层物化聚合保留原始数据，API 层 `ADVISOR_RATING_MIN_SAMPLES=8` 过滤小样本维度值，前端 `RatingSummary.vue` 统一阈值口径。
- **兴趣探索**：8 个研究场景多选 → 静态映射表确定性推导候选方向（10 方向池取 top-5），零 LLM 依赖；选定方向写回画像 `research_interests`。前端 `InterestExplorationCard.vue`。
- **招募社区增强**：招募详情页、评论 + 点赞 + 举报（内容审核）、404 页。
- **客观四维雷达**：`ChartPanel.vue` 以证据治理数据展示客观维度 top3，无证据只显示"暂无证据"提示（替代原六维特质条）。
- **访谈表达层增强**（`chat_expression.py`，+570 行/4 文件）：LLM 基于确定性事实包整段重写访谈回复；校验闸门（非空/≤400 字/禁词/选项 label 全覆盖/题面核心片段覆盖）；无凭据 `disabled`、失败超时 `unavailable` 完全降级回固定模板；诚实性红线（画像确认门与匹配结果不增强）；平台探测跳过。专项测试 17 用例。
- **迁移 0012**：mentor_campus_card 表。
- **路由白名单同步**：`public-route-allowlist.json` + `web-api.caddy` 覆盖全部新路由；生产强制 `MAIL_MODE=smtp`、密码仅经 `MAIL_PASSWORD_FILE` 挂载。

### 变更

- 清理 legacy/mock/milvus 遗留代码。
- **测试去冗余**：删除 3 个零引用的 dep3 验证脚本（`dep3_s3_tamper_helper.py` / `dep3_verify_postgres_concurrency.py` / `dep3_verify_real_s3.py`，其场景已被单测覆盖）；`test_api.py` 剔除 6 个已被更深层测试覆盖的重复用例（导师列表空态/散点空态/招募列表/招募提交/训练触发×2），保留 14 个唯一守门用例；移除与 conftest 冲突的误导性 `DATABASE_URL` 覆盖。

### 验证

- 后端全量：540 passed（19 项 docker 依赖用例在无 docker 环境失败，与基线一致）。
- 表达层专项：`test_chat_expression.py` 13 用例 + `test_qxd_contract.py` 表达层 4 用例全过。
- 前端：vue-tsc / eslint 干净，生产构建成功。

---

## v2.2.0（2026-07-27，审计补丁基线）

# Tsing-RADAR 审计补丁变更日志

> 日期：2026-07-27
> 基于审计报告的全部补丁已应用到本目录
> 所有修改处均以 `// [PATCH]` 或 `# [PATCH]` 注释标注

---

## 一、修改文件清单（共 17 个文件，含 2 个新增）

| # | 文件路径 | 类型 | 修改摘要 |
|---|---------|------|---------|
| 1 | `frontend/src/api/advisor.ts` | 修改 | 修复 legacyChat 路径前缀 |
| 2 | `frontend/src/api/chat.ts` | 修改 | SSE 解析改为 OpenAI 格式 |
| 3 | `frontend/src/api/request.ts` | 修改 | 响应拦截器支持统一响应封装 |
| 4 | `frontend/src/types/advisor.ts` | 修改 | 移除 SortMetric 中不支持的 synergy |
| 5 | `frontend/vite.config.ts` | 修改 | 移除多余的 /v1 代理配置 |
| 6 | `backend/app/api/v1/llm.py` | 修改 | SSE 帧格式改为 OpenAI 兼容 |
| 7 | `backend/app/api/v1/chat.py` | 修改 | /v1/chat/completions 改为标准 OpenAI 协议 |
| 8 | `backend/app/api/v1/advisor.py` | 修改 | 添加分页参数 page/size |
| 9 | `backend/app/api/v1/recruitment.py` | 修改 | 响应结构包装 + 注入鉴权 |
| 10 | `backend/app/api/v1/feedback.py` | 修改 | 注入鉴权依赖 |
| 11 | `backend/app/api/v1/resume.py` | 修改 | 注入鉴权 + x_soda.attachments 支持 |
| 12 | `backend/app/api/v1/train.py` | 修改 | admin_token 改为 Header 传递 |
| 13 | `backend/app/core/deps.py` | 修改 | 增强鉴权日志 |
| 14 | `backend/app/core/response.py` | **新增** | 统一响应封装与全局异常处理 |
| 15 | `backend/app/schemas/qxd.py` | **新增** | OpenAI 兼容协议 Schema 定义 |
| 16 | `backend/app/schemas/advisor.py` | 修改 | LLMChatRequest 增加 model/stream 字段 |
| 17 | `backend/app/schemas/__init__.py` | 修改 | 同步导出新 Schema |
| 18 | `backend/app/schemas/train.py` | 修改 | 移除 admin_token 字段 |
| 19 | `backend/app/main.py` | 修改 | 注册全局异常处理器 + 更新路由清单 |

---

## 二、补丁详情

### 补丁 1：修复 legacyChat 路径前缀 [严重]

**文件：** `frontend/src/api/advisor.ts`

**问题：** 前端调用 `/v1/chat/completions`，但后端所有路由注册在 `/api` 前缀下，实际路径是 `/api/v1/chat/completions`，导致 404。

**修改：**
```diff
-}>('/v1/chat/completions', { interest })
+}>('/api/v1/chat/completions', { interest })
```

---

### 补丁 2：修复 SSE 流式格式为 OpenAI 兼容 [严重]

**文件：** `backend/app/api/v1/llm.py` + `frontend/src/api/chat.ts`

**问题：** 后端 SSE 使用自定义格式 `{"delta":"...", "finish":true}`，清小搭平台期望标准 OpenAI 格式 `{"choices":[{"delta":{"content":"..."}}]}` + `data: [DONE]`。

**后端修改：**
- delta 帧改为 `{"choices":[{"delta":{"content":"..."}}]}`
- 终止帧改为 `{"choices":[{"finish_reason":"stop"}], "x_soda":{...}}`
- 末尾追加 `data: [DONE]`

**前端修改：**
- 解析逻辑改为 `data.choices[0].delta.content`
- 终止判定改为 `data.choices[0].finish_reason === "stop"`
- 兼容 `data: [DONE]` 信号

---

### 补丁 3：修复 /v1/chat/completions 请求体协议 [严重]

**文件：** `backend/app/api/v1/chat.py` + `backend/app/schemas/qxd.py`（新增）

**问题：** 后端接收 `MatchRequest({interest, portrait, weight})`，但清小搭会发标准 OpenAI 格式 `{model, messages, stream}`。

**修改：**
- 新增 `OpenAIChatRequest` Schema，含 `model/messages/stream/temperature/max_tokens`
- 后端从 `req.messages` 提取用户最后一条消息作为 interest
- 响应改为标准 `OpenAIChatResponse` 格式

---

### 补丁 4：注入鉴权依赖 [严重]

**文件：** `backend/app/api/v1/recruitment.py`、`feedback.py`、`resume.py`、`train.py`

**问题：** `get_current_student` 和 `verify_admin` 定义了但从未使用，`X-Student-Token` 头形同虚设。

**修改：**
- `POST /api/recruitments` → 添加 `Depends(get_current_student)`
- `POST /api/feedback` → 添加 `Depends(get_current_student)`
- `POST /api/resume/submit` → 添加 `Depends(get_current_student)`
- `POST /api/train/trigger` → 改用 `Depends(verify_admin)`，admin_token 从 Header 传递

---

### 补丁 5：修复 GET /api/recruitments 响应结构 [中等]

**文件：** `backend/app/api/v1/recruitment.py`

**问题：** 后端返回裸 `list`，前端期望 `{ data: RecruitmentItem[] }`。

**修改：**
```diff
-    return result  # ← 裸 list
+    return {"data": result}  # ← 包装为 { data: [...] }
```

---

### 补丁 6：为列表接口添加分页 [中等]

**文件：** `backend/app/api/v1/advisor.py`

**问题：** GET /api/mentors 全量返回，数据量大时有性能风险。

**修改：**
- 添加 `page: int = Query(1, ge=1)` 和 `size: int = Query(50, ge=1, le=200)` 参数
- 响应增加 `total/page/size` 字段

---

### 补丁 7：移除 SortMetric 中不支持的 synergy [低]

**文件：** `frontend/src/types/advisor.ts`

**问题：** 前端 `SortMetric` 包含 `synergy`，但后端 `SORT_METRICS` 不含此项，传该值会返回 400。

**修改：** 从 `SortMetric` 联合类型中移除 `'synergy'`。

---

### 补丁 8：统一响应封装与全局异常处理 [中等]

**文件：** `backend/app/core/response.py`（新增）、`backend/app/main.py`

**问题：** 各路由手动拼装错误响应，格式不统一。

**修改：**
- 新增 `BizError` 业务异常类
- 新增 `success()` 统一成功响应封装
- 注册 3 个全局异常处理器：`BizError` / `RequestValidationError` / 通用 `Exception`
- 前端 `request.ts` 拦截器兼容 `{ code, message, data }` 格式

---

### 补丁 9：添加 x_soda.attachments 多模态附件支持 [中等]

**文件：** `backend/app/api/v1/resume.py`、`backend/app/schemas/qxd.py`

**问题：** 清小搭多模态附件协议要求 agent 产出的文件通过 `x_soda.attachments` 字段回传，原项目未实现。

**修改：**
- 新增 `Attachment` Schema（含 `fileUrl/fileName/fileType/mimeType` 4 必填 + 3 选填）
- `POST /api/resume/generate` 响应自动构造附件元数据

---

### 补丁 10：修复 Vite proxy 配置 [低]

**文件：** `frontend/vite.config.ts`

**问题：** `/v1` 代理配置无实际对应路由（后端统一注册在 `/api` 前缀下）。

**修改：** 移除 `/v1` 代理条目。

---

### 补丁 11：admin_token 改为 Header 传递 [中等]

**文件：** `backend/app/api/v1/train.py`、`backend/app/schemas/train.py`

**问题：** 原设计将 `admin_token` 放在请求体中，不符合 RESTful 安全实践。

**修改：**
- `train.py` 改用 `Depends(verify_admin)`，通过 `X-Admin-Token` Header 校验
- `train.py` Schema 移除 `admin_token` 字段

---

### 补丁 12：LLMChatRequest 增加 model/stream 字段

**文件：** `backend/app/schemas/advisor.py`

**问题：** 清小搭发送的 OpenAI 格式请求包含 `model` 和 `stream` 字段，原 Schema 不接受。

**修改：** 增加 `model: Optional[str]` 和 `stream: Optional[bool]` 字段。

---

## 三、验证结果

### 后端验证
```
Backend import OK
  GET    /api/mentors          (含分页)
  GET    /api/mentors/sort
  GET    /api/v1/models
  POST   /api/v1/chat/completions  (OpenAI 协议)
  POST   /api/feedback          (含鉴权)
  POST   /api/v1/llm/chat       (OpenAI SSE)
  POST   /api/v1/llm/embeddings
  POST   /api/match
  GET    /api/recruitments      (含 { data: [...] })
  POST   /api/recruitments      (含鉴权)
  POST   /api/resume/generate   (含 x_soda.attachments)
  POST   /api/resume/submit     (含鉴权)
  GET    /api/scatter
  POST   /api/train/trigger     (X-Admin-Token Header)
  GET    /api/tsinghua/auth/verify
  GET    /api/tsinghua/lib/papers
  POST   /api/internal/scrape/faculty
  GET    /
  GET    /health
```

所有 22 条路由正常注册，无 import 错误。

---

## 四、后续待办（审计报告第七章）

以下接口在技术文档中规划但尚未实现，本次补丁未包含（需业务逻辑设计）：

| 接口 | 说明 |
|------|------|
| `POST /api/resume/upload` | 上传 PDF/Word 简历文件 |
| `GET /api/report/export` | 导出匹配报告 (Markdown/PDF) |
| `POST /api/contact/advisor` | 一键联系导师 (邮件) |
| `GET /api/tsinghua/assessment` | 对接学业志趣自测 API |
| `GET /api/tsinghua/lib/papers` | 替换 stub 为真实校内数据源 |
