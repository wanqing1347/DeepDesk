export type ResearchStepStatus = 'running' | 'complete' | 'paused'

export interface ResearchStep {
  label: string
  status: ResearchStepStatus
}

export interface ResearchProgressState {
  heading: string
  steps: ResearchStep[]
  subdued: boolean
  paused: boolean
}

const STAGES = [
  {
    label: 'Understand the question',
    patterns: ['正在分析您的需求', '需求分析完成', '信息充足，准备生成研究主题', '正在生成研究主题', '研究主题已生成'],
  },
  {
    label: 'Build the research plan',
    patterns: ['轮研究开始', '正在生成执行计划', '执行计划已生成', '执行计划表'],
  },
  {
    label: 'Research the topic',
    patterns: ['开始执行任务', '正在执行任务', '执行结果:', '任务执行完成'],
  },
  {
    label: 'Review the findings',
    patterns: ['正在评估当前研究结果', '研究结果评估通过', '研究结果评估未通过', '准备进入下一轮迭代'],
  },
  {
    label: 'Final synthesis',
    patterns: ['研究阶段完成，准备生成最终报告', '正在生成最终研究报告'],
  },
] as const

function lastStageIndex(text: string, patterns: readonly string[]): number {
  return Math.max(...patterns.map((pattern) => text.lastIndexOf(pattern)))
}

export function researchProgressState(thinking: string, content: string, streaming: boolean): ResearchProgressState {
  const paused = content.trimStart().startsWith('⏸【暂停深入研究】')
  const observed = STAGES
    .map((stage) => ({ ...stage, lastIndex: lastStageIndex(thinking, stage.patterns) }))
    .filter((stage) => stage.lastIndex >= 0)

  if (paused) {
    return {
      heading: 'Research paused',
      steps: [
        ...(observed.length ? [{ label: STAGES[0].label, status: 'complete' as const }] : []),
        { label: 'Waiting for clarification', status: 'paused' },
      ],
      subdued: false,
      paused: true,
    }
  }

  const currentStage = observed.reduce<(typeof observed)[number] | undefined>(
    (latest, stage) => (!latest || stage.lastIndex > latest.lastIndex ? stage : latest),
    undefined,
  )
  const steps = observed.map((stage) => ({
    label: stage.label,
    status: streaming && stage.label === currentStage?.label ? ('running' as const) : ('complete' as const),
  }))
  const finalObserved = observed.some((stage) => stage.label === 'Final synthesis')

  return {
    heading: !streaming && steps.length ? 'Research complete' : 'Researching',
    steps,
    subdued: Boolean(content.trim()) && finalObserved,
    paused: false,
  }
}
