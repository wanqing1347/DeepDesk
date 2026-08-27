import { describe, expect, it } from 'vitest'
import { pptProgressState, presentationFileFromContent } from './pptProgress'

describe('pptProgressState', () => {
  it('tracks the real CREATE flow without inventing unseen stages', () => {
    const thinking = [
      '开始创建新的PPT...',
      '正在分析您的需求...',
      '✅ 需求已确认，开始收集相关信息',
      '正在收集相关信息...',
      '✅相关信息收集完成，开始选择模板',
      '正在设计模板样式...',
      '✅ 模板设计完成，开始生成大纲',
      '正在生成PPT大纲...',
    ].join('\n')

    expect(pptProgressState(thinking, '', 'streaming')).toEqual({
      heading: 'Preparing presentation',
      steps: [
        { label: 'Requirement', status: 'complete' },
        { label: 'Research', status: 'complete' },
        { label: 'Template', status: 'complete' },
        { label: 'Outline', status: 'running' },
      ],
      paused: false,
      failed: false,
      stopped: false,
      file: null,
    })
  })

  it('keeps Requirement paused when the backend asks for clarification', () => {
    const progress = pptProgressState(
      '开始创建新的PPT...\n正在分析您的需求...\n【暂停生成PPT】请说明受众和页数。',
      '需要补充信息后才能继续生成演示文稿。',
      'complete',
    )

    expect(progress.heading).toBe('Presentation paused')
    expect(progress.steps).toEqual([{ label: 'Requirement', status: 'paused' }])
    expect(progress.paused).toBe(true)
  })

  it('marks the actual failed stage instead of completing it optimistically', () => {
    const thinking = [
      '正在分析您的需求...',
      '需求已确认',
      '正在收集相关信息...',
      '信息收集完成',
      '正在设计模板样式...',
      '模板设计完成',
      '正在生成PPT大纲...',
      '大纲生成完成',
      '正在设计PPT详细内容...',
      'PPT内容设计完成',
      '正在渲染PPT...',
    ].join('\n')

    const progress = pptProgressState(thinking, 'PPT渲染失败，请重试。', 'complete')

    expect(progress.heading).toBe('Presentation failed')
    expect(progress.steps.at(-1)).toEqual({ label: 'Render', status: 'failed' })
    expect(progress.failed).toBe(true)
  })

  it('shows MODIFY as an update flow rather than replaying Requirement through Outline', () => {
    const thinking = [
      '正在修改PPT...',
      '正在分析修改需求...',
      '正在修改PPT内容...',
      '正在重新生成PPT详细内容...',
      '✅PPT内容设计完成，开始生成图片素材',
    ].join('\n')

    const progress = pptProgressState(thinking, '', 'streaming')

    expect(progress.heading).toBe('Updating presentation')
    expect(progress.steps).toEqual([
      { label: 'Update slides', status: 'complete' },
      { label: 'Images', status: 'running' },
    ])
  })

  it('shows RESUME from the real stage reached after the resume marker', () => {
    const thinking = '正在从状态 OUTLINE 继续执行PPT生成...\n正在生成PPT大纲...\n'
    const progress = pptProgressState(thinking, '', 'streaming')

    expect(progress.heading).toBe('Resuming presentation')
    expect(progress.steps).toEqual([{ label: 'Outline', status: 'running' }])
  })

  it('marks the active stage stopped when generation is stopped', () => {
    const progress = pptProgressState('正在设计模板样式...', '', 'stopped')

    expect(progress.heading).toBe('Presentation stopped')
    expect(progress.steps).toEqual([{ label: 'Template', status: 'stopped' }])
  })

  it('marks the active stage failed on a transport or SSE terminal error', () => {
    const progress = pptProgressState('正在收集相关信息...', '', 'error')

    expect(progress.heading).toBe('Presentation failed')
    expect(progress.steps).toEqual([{ label: 'Research', status: 'failed' }])
  })
})

describe('presentationFileFromContent', () => {
  it('only promotes a real pptx URL and exposes a readable filename', () => {
    const content = [
      '参考资料：https://example.com/report',
      'PPT 已生成：https://127.0.0.1:9000/rag-test2/ppt/demo/ppt_42_abcd1234.pptx',
    ].join('\n')

    expect(presentationFileFromContent(content)).toEqual({
      url: 'https://127.0.0.1:9000/rag-test2/ppt/demo/ppt_42_abcd1234.pptx',
      name: 'ppt_42_abcd1234.pptx',
    })
  })

  it('does not treat an arbitrary URL as a presentation file', () => {
    expect(presentationFileFromContent('See https://example.com/report for details.')).toBeNull()
  })

  it('keeps the real file URL when the presentation completes', () => {
    const content = 'PPT已生成：http://127.0.0.1:9000/rag-test2/ppt/c1/ppt_7_demo.pptx'
    const progress = pptProgressState('正在渲染PPT...\n✅ PPT渲染完成', content, 'complete')

    expect(progress.heading).toBe('Presentation ready')
    expect(progress.file?.name).toBe('ppt_7_demo.pptx')
    expect(progress.steps).toEqual([{ label: 'Render', status: 'complete' }])
  })
})
