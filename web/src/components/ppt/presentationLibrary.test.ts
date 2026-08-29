import { describe, expect, it } from 'vitest'
import type { PresentationInfo } from '../../types/api'
import {
  presentationFileName,
  presentationLibraryItems,
  presentationStatusLabel,
  presentationStatusTone,
  presentationTitle,
} from './presentationLibrary'

const older: PresentationInfo = {
  id: 1,
  conversationId: 'ppt-conv-1',
  status: 'SUCCESS',
  query: 'AI interview walkthrough',
  fileUrl: 'http://localhost:9000/rag-test2/ppt/ppt-conv-1/ppt_1_demo.pptx',
  createTime: '2026-08-27T10:00:00',
  updateTime: '2026-08-27T10:05:00',
}

const newer: PresentationInfo = {
  id: 2,
  conversationId: 'ppt-conv-2',
  status: 'RENDER',
  query: 'Research summary deck',
  createTime: '2026-08-28T12:00:00',
  updateTime: '2026-08-28T12:03:00',
}

describe('presentation library', () => {
  it('sorts recent assets first and searches title, file, conversation, and status', () => {
    expect(presentationLibraryItems([older, newer]).map((item) => item.id)).toEqual([2, 1])
    expect(presentationLibraryItems([older, newer], 'interview').map((item) => item.id)).toEqual([1])
    expect(presentationLibraryItems([older, newer], 'ppt_1_demo').map((item) => item.id)).toEqual([1])
    expect(presentationLibraryItems([older, newer], 'ppt-conv-2').map((item) => item.id)).toEqual([2])
    expect(presentationLibraryItems([older, newer], 'rendering').map((item) => item.id)).toEqual([2])
  })

  it('exposes readable titles, filenames, and status labels', () => {
    expect(presentationTitle(older)).toBe('AI interview walkthrough')
    expect(presentationFileName(older)).toBe('ppt_1_demo.pptx')
    expect(presentationFileName(newer)).toBe('No generated file')
    expect(presentationStatusLabel('SUCCESS')).toBe('Ready')
    expect(presentationStatusLabel('FAILED')).toBe('Failed')
    expect(presentationStatusLabel('SCHEMA')).toBe('Designing slides')
    expect(presentationStatusTone('SUCCESS')).toBe('ready')
    expect(presentationStatusTone('FAILED')).toBe('failed')
    expect(presentationStatusTone('OUTLINE')).toBe('active')
  })

  it('falls back to the generated filename or an untitled label', () => {
    expect(
      presentationTitle({
        id: 3,
        status: 'SUCCESS',
        fileUrl: 'https://files.test/ppt/My%20Deck.pptx',
      }),
    ).toBe('My Deck')
    expect(presentationTitle({ id: 4, status: 'INIT' })).toBe('Untitled presentation')
  })
})
