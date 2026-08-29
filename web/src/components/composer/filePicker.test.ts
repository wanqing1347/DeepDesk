import { describe, expect, it } from 'vitest'
import type { FileList } from '../../types/api'
import { filePickerItems, filePickerSelectable } from './filePicker'

describe('file picker', () => {
  it('sorts files by newest first', () => {
    const list: FileList = {
      count: 3,
      files: {
        old: {
          fileId: 'old',
          fileName: 'old.pdf',
          status: 'SUCCESS',
          createdAt: '2026-08-20T10:00:00Z',
        },
        newest: {
          fileId: 'newest',
          fileName: 'newest.pdf',
          status: 'SUCCESS',
          createdAt: '2026-08-28T10:00:00Z',
        },
        middle: {
          fileId: 'middle',
          fileName: 'middle.pdf',
          status: 'SUCCESS',
          createdAt: '2026-08-25T10:00:00Z',
        },
      },
    }

    expect(filePickerItems(list).map((file) => file.fileId)).toEqual(['newest', 'middle', 'old'])
  })

  it('only allows processed files to be selected', () => {
    expect(filePickerSelectable({ fileId: 'ready', fileName: 'ready.pdf', status: 'SUCCESS' })).toBe(true)
    expect(filePickerSelectable({ fileId: 'processing', fileName: 'processing.pdf', status: 'PROCESSING' })).toBe(false)
    expect(filePickerSelectable({ fileId: 'failed', fileName: 'failed.pdf', status: 'FAILED' })).toBe(false)
  })
})
