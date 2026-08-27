import { describe, expect, it } from 'vitest'
import { researchProgressState } from './researchProgress'

describe('researchProgressState', () => {
  it('tracks the real Deep Research stage markers while streaming', () => {
    const thinking = [
      '🔍 正在分析您的需求...',
      '✅ 需求分析完成',
      '📝 正在生成研究主题...',
      '✅ 研究主题已生成',
      '🔄 第 1 轮研究开始',
      '📋 正在生成执行计划...',
      '✅ 执行计划已生成，共 3 个任务',
      '--- 开始执行任务 ---',
      '--- 任务执行完成 ---',
      '🔍 正在评估当前研究结果...',
    ].join('\n')

    expect(researchProgressState(thinking, '', true)).toEqual({
      heading: 'Researching',
      steps: [
        { label: 'Understand the question', status: 'complete' },
        { label: 'Build the research plan', status: 'complete' },
        { label: 'Research the topic', status: 'complete' },
        { label: 'Review the findings', status: 'running' },
      ],
      subdued: false,
      paused: false,
    })
  })

  it('shows the real clarification pause instead of pretending research completed', () => {
    const progress = researchProgressState(
      '🔍 正在分析您的需求...\n✅ 需求分析完成\n',
      '⏸【暂停深入研究】请说明研究对象。',
      false,
    )

    expect(progress).toEqual({
      heading: 'Research paused',
      steps: [
        { label: 'Understand the question', status: 'complete' },
        { label: 'Waiting for clarification', status: 'paused' },
      ],
      subdued: false,
      paused: true,
    })
  })

  it('shows a repeated research round as the current real stage', () => {
    const thinking = [
      '正在分析您的需求',
      '第 1 轮研究开始',
      '开始执行任务',
      '正在评估当前研究结果',
      '研究结果评估未通过',
      '准备进入下一轮迭代',
      '第 2 轮研究开始',
      '正在生成执行计划',
    ].join('\n')

    const progress = researchProgressState(thinking, '', true)

    expect(progress.steps).toEqual([
      { label: 'Understand the question', status: 'complete' },
      { label: 'Build the research plan', status: 'running' },
      { label: 'Research the topic', status: 'complete' },
      { label: 'Review the findings', status: 'complete' },
    ])
  })

  it('subdues progress after final report text starts streaming', () => {
    const thinking = [
      '正在分析您的需求',
      '正在生成执行计划',
      '开始执行任务',
      '正在评估当前研究结果',
      '研究阶段完成，准备生成最终报告',
      '📝 正在生成最终研究报告...',
    ].join('\n')

    const progress = researchProgressState(thinking, '# Final report\nFirst paragraph', true)

    expect(progress.subdued).toBe(true)
    expect(progress.steps.at(-1)).toEqual({ label: 'Final synthesis', status: 'running' })
  })

  it('marks every observed stage complete when the response terminates', () => {
    const thinking = '正在分析您的需求\n正在生成执行计划\n开始执行任务\n正在评估当前研究结果\n正在生成最终研究报告'
    const progress = researchProgressState(thinking, 'report', false)

    expect(progress.heading).toBe('Research complete')
    expect(progress.steps.every((step) => step.status === 'complete')).toBe(true)
  })
})
