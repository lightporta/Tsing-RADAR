import advisorsRaw from './mentors.json'
import type { Advisor, MatchedAdvisor } from '@/types/advisor'
import type { RecruitmentItem } from '@/types/api'

// =====================================================================
// 前端 Mock 数据服务（文档 §7.3）
// 当 VITE_USE_MOCK=true 时启用，前端可完全独立于后端开发
// A2：旧 Mock 缺少来源与授权证据，当前数据集为空；不得绕过后端发布门。
// =====================================================================

// 历史 JSON 只保留作视觉开发资产，运行时 Mock 不把它冒充已审核数据。
void advisorsRaw
export const mockAdvisors: Advisor[] = []

/** Mock 不得制造导师推荐，只保留空数据 UX。 */
export function mockMatch(_interest: string): MatchedAdvisor[] {
  return []
}

/** Mock 招募列表（从导师 recruitments 字段聚合） */
export const mockRecruitments: RecruitmentItem[] = mockAdvisors.flatMap((m) =>
  (m.recruitments || []).map((r) => ({
    recruit_id: `static_${m.name}_${r.title.slice(0, 6)}`,
    publisher_name: m.name,
    publisher_type: 'advisor' as const,
    type: r.type,
    title: r.title,
    req: r.req,
    major: r.major,
    deadline: r.deadline,
    is_urgent: !!r.is_urgent,
    dept: m.dept,
  })),
)

// =====================================================================
// Mock 对话回复（本地 stub，规则与后端 _stub_reply 对齐）
// =====================================================================

const STUB_RULES: Array<[string[], string]> = [
  [['nlp', '自然语言', '文本', '对话系统', '语言模型', 'llm'],
   '你提到对 NLP 感兴趣，能说说你具体对哪个子方向更感兴趣吗？比如**机器翻译**、**对话系统**还是**知识图谱**？'],
  [['cv', '计算机视觉', '图像', '视觉', '目标检测', '分割'],
   '关于计算机视觉，你更偏向**基础研究**（如检测、分割、生成）还是**应用落地**（如自动驾驶、工业质检）？'],
  [['机器人', 'robot', '控制', '机械臂', '运动'],
   '机器人方向上，你更想做**运动控制与感知融合**，还是**强化学习/仿真训练**？'],
  [['机器学习', '深度学习', 'ml', 'dl', '模型', '算法'],
   '在机器学习里，你更看重**理论**（优化、泛化）还是**工程**（系统、大模型训练）？'],
  [['系统', '分布式', '数据库', '编译', '操作系统', '体系结构'],
   '系统方向你的偏好是偏**底层**（编译/体系结构）还是偏**上层**（分布式/数据库）？'],
  [['信号', '通信', '射频', '雷达', '电磁', '天线'],
   '通信与信号方向，你更想做**硬件**（射频/天线）还是**算法**（估计/检测/信号处理）？'],
  [['芯片', 'eda', '集成电路', '半导体', 'verilog'],
   '芯片方向你倾向**数字前端/后端**，还是**模拟/射频电路设计**？'],
  [['科研', '论文', '学术', 'phd', '读博'],
   '你更看重导师的**学术指导**（手把手带）还是**给资源让你自由探索**？'],
  [['实习', '工业', '企业', '就业', '工作'],
   '你希望导师项目偏**校企合作**（便于实习就业）还是偏**国家级科研**（便于发论文/读博）？'],
]

const FALLBACKS = [
  '除了你提到的方向，你对导师的**指导风格**（手把手 vs 自由探索）有什么偏好吗？',
  '你更看重**科研氛围包容度**，还是**出成果的效率**？',
  '你希望导师的**项目经费/资源**充足，还是更在意**学术网络与人脉**？',
  '你对**国有机构方向**（航天/军工/国家实验室）和**私营方向**（互联网/初创）有偏好吗？',
  '能具体说说你最看重的科研特质吗？比如**学术敏锐度、人脉资源、指导意愿、性格包容度、经费、产出效率**。',
]

export function mockChatReply(input: string, userTurns: number): string {
  const lower = input.toLowerCase()
  const completionSignals = ['推荐', '够了', '完了', '可以了', '结束', 'match', 'recommend', '开始匹配', '好了', '差不多了']

  if (completionSignals.some((s) => lower.includes(s)) && userTurns >= 2) {
    return (
      'Mock 模式不保存访谈状态，也不能确认画像。' +
      '请连接后端后继续完整的动态访谈流程。'
    )
  }

  for (const [keys, reply] of STUB_RULES) {
    if (keys.some((k) => lower.includes(k))) return reply
  }

  return FALLBACKS[userTurns % FALLBACKS.length]
}
