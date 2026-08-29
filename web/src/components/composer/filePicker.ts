import type { FileInfo, FileList } from '../../types/api'

function timestamp(value?: string | null): number {
  const parsed = value ? Date.parse(value) : Number.NaN
  return Number.isNaN(parsed) ? 0 : parsed
}

export function filePickerItems(list: FileList): FileInfo[] {
  return Object.values(list.files).sort((left, right) => {
    const timeDiff = timestamp(right.createdAt) - timestamp(left.createdAt)
    if (timeDiff !== 0) return timeDiff
    return left.fileName.localeCompare(right.fileName)
  })
}

export function filePickerSelectable(file: FileInfo): boolean {
  return file.status.trim().toUpperCase() === 'SUCCESS'
}
