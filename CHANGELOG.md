# Tsing-RADAR 变更日志

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
