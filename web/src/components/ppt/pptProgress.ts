import type { MessageState } from '../../types/agent'

export type PptStepStatus = 'running' | 'complete' | 'paused' | 'failed' | 'stopped'

export interface PptStep {
  label: string
  status: PptStepStatus
}

export interface PresentationFile {
  url: string
  name: string
}

export interface PptProgressState {
  heading: string
  steps: PptStep[]
  paused: boolean
  failed: boolean
  stopped: boolean
  file: PresentationFile | null
}

interface StageDefinition {
  label: string
  patterns: readonly string[]
}

const CREATE_STAGES: readonly StageDefinition[] = [
  { label: 'Requirement', patterns: ['正在分析您的需求', '需求已确认'] },
  { label: 'Research', patterns: ['正在收集相关信息', '相关信息收集完成', '信息收集完成'] },
  { label: 'Template', patterns: ['正在设计模板样式', '模板设计完成'] },
  { label: 'Outline', patterns: ['正在生成PPT大纲', '大纲生成完成'] },
  { label: 'Slides', patterns: ['正在设计PPT详细内容', 'PPT内容设计完成'] },
  { label: 'Images', patterns: ['开始生成图片素材', '共需生成', '图片生成完成', '所有图片生成完成', '素材准备就绪'] },
  { label: 'Render', patterns: ['正在渲染PPT', 'PPT渲染完成'] },
]

const MODIFY_STAGES: readonly StageDefinition[] = [
  {
    label: 'Update slides',
    patterns: ['正在分析修改需求', '正在修改PPT内容', '正在重新生成PPT详细内容', 'PPT内容设计完成'],
  },
  { label: 'Images', patterns: ['开始生成图片素材', '共需生成', '图片生成完成', '所有图片生成完成', '素材准备就绪'] },
  { label: 'Render', patterns: ['正在渲染PPT', 'PPT渲染完成'] },
]

const FAILURE_STAGE_PATTERNS: readonly StageDefinition[] = [
  { label: 'Requirement', patterns: ['需求分析失败', '需求信息不足'] },
  { label: 'Research', patterns: ['信息收集失败', '资料收集失败'] },
  { label: 'Template', patterns: ['模板选择失败', '没有可用PPT模板', '模板不存在'] },
  { label: 'Outline', patterns: ['大纲生成失败'] },
  { label: 'Slides', patterns: ['Schema生成失败', 'Schema 生成失败', '详细内容生成失败'] },
  { label: 'Update slides', patterns: ['Schema生成失败', 'Schema 生成失败', '修改失败'] },
  { label: 'Render', patterns: ['PPT渲染失败', '渲染失败'] },
]

const TERMINAL_FAILURE_PATTERNS = [
  'PPT生成未完成',
  'PPT 生成未完成',
  'PPT生成失败',
  '生成失败',
  '渲染失败',
  '无法继续',
  '无法生成',
  '无法修改',
  '未能生成',
  '未能完成',
  '没有可用PPT模板',
  '模板不存在',
]

function lastStageIndex(text: string, patterns: readonly string[]): number {
  return Math.max(...patterns.map((pattern) => text.lastIndexOf(pattern)))
}

function isModifyRun(thinking: string): boolean {
  return thinking.includes('正在修改PPT') || thinking.includes('正在分析修改需求') || thinking.includes('正在重新生成PPT详细内容')
}

function isResumeRun(thinking: string): boolean {
  return thinking.includes('正在从状态') && thinking.includes('继续执行PPT生成')
}

function isRequirementPause(thinking: string, content: string): boolean {
  if (thinking.toLowerCase().includes('【暂停生成ppt】')) return true
  const normalized = content.trim()
  return normalized.includes('需要补充信息') || normalized.includes('请补充') || normalized.includes('补充必要信息')
}

function isTerminalFailure(content: string): boolean {
  return TERMINAL_FAILURE_PATTERNS.some((pattern) => content.includes(pattern))
}

function failureStageLabel(content: string): string | null {
  const match = FAILURE_STAGE_PATTERNS.find((stage) => stage.patterns.some((pattern) => content.includes(pattern)))
  return match?.label ?? null
}

function fileNameFromUrl(url: string): string {
  try {
    const pathname = decodeURIComponent(new URL(url).pathname)
    const name = pathname.split('/').filter(Boolean).at(-1)
    return name || 'presentation.pptx'
  } catch {
    return 'presentation.pptx'
  }
}

export function presentationFileFromContent(content: string): PresentationFile | null {
  const matches = content.match(/https?:\/\/[^\s)\]}>'"]+/gi) ?? []
  for (const candidate of matches) {
    const url = candidate.replace(/[.,;!?，。；！？]+$/, '')
    try {
      const parsed = new URL(url)
      if (!decodeURIComponent(parsed.pathname).toLowerCase().endsWith('.pptx')) continue
      return { url, name: fileNameFromUrl(url) }
    } catch {
      // Ignore malformed URLs emitted as plain text.
    }
  }
  return null
}

export function pptProgressState(thinking: string, content: string, state: MessageState): PptProgressState {
  const file = presentationFileFromContent(content)
  const paused = state === 'complete' && !file && isRequirementPause(thinking, content)
  const failed = !file && (state === 'error' || (state === 'complete' && !paused && isTerminalFailure(content)))
  const stopped = state === 'stopped'
  const streaming = state === 'streaming'
  const stages = isModifyRun(thinking) ? MODIFY_STAGES : CREATE_STAGES
  const observed = stages
    .map((stage) => ({ ...stage, lastIndex: lastStageIndex(thinking, stage.patterns) }))
    .filter((stage) => stage.lastIndex >= 0)
  const currentStage = observed.reduce<(typeof observed)[number] | undefined>(
    (latest, stage) => (!latest || stage.lastIndex > latest.lastIndex ? stage : latest),
    undefined,
  )
  const explicitFailureLabel = failureStageLabel(content)

  const steps: PptStep[] = observed.map((stage) => {
    if (stage.label !== currentStage?.label) return { label: stage.label, status: 'complete' }
    if (paused && stage.label === 'Requirement') return { label: stage.label, status: 'paused' }
    if (failed && (!explicitFailureLabel || explicitFailureLabel === stage.label)) return { label: stage.label, status: 'failed' }
    if (stopped) return { label: stage.label, status: 'stopped' }
    if (streaming) return { label: stage.label, status: 'running' }
    return { label: stage.label, status: 'complete' }
  })

  if (failed && explicitFailureLabel && !steps.some((step) => step.status === 'failed')) {
    const explicitStep = steps.find((step) => step.label === explicitFailureLabel)
    if (explicitStep) explicitStep.status = 'failed'
  }

  let heading = 'Preparing presentation'
  if (file && state === 'complete') heading = 'Presentation ready'
  else if (paused) heading = 'Presentation paused'
  else if (failed) heading = 'Presentation failed'
  else if (stopped) heading = 'Presentation stopped'
  else if (isModifyRun(thinking)) heading = 'Updating presentation'
  else if (isResumeRun(thinking)) heading = 'Resuming presentation'
  else if (state === 'complete' && steps.length) heading = 'Presentation complete'

  return { heading, steps, paused, failed, stopped, file }
}
