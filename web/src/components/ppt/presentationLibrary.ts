import type { PresentationInfo } from '../../types/api'

export type PresentationStatusTone = 'ready' | 'failed' | 'active'

function timestamp(item: PresentationInfo): number {
  const raw = item.updateTime || item.createTime
  if (!raw) return 0
  const value = new Date(raw).getTime()
  return Number.isNaN(value) ? 0 : value
}

export function presentationFileName(item: PresentationInfo): string {
  const raw = item.fileUrl?.trim()
  if (!raw) return 'No generated file'
  try {
    const url = new URL(raw, 'http://localhost')
    const name = decodeURIComponent(url.pathname.split('/').filter(Boolean).pop() || '')
    return name || 'presentation.pptx'
  } catch {
    const name = raw.split(/[?#]/, 1)[0]?.split('/').filter(Boolean).pop()
    return name || 'presentation.pptx'
  }
}

export function presentationTitle(item: PresentationInfo): string {
  return item.query?.trim() || (item.fileUrl ? presentationFileName(item).replace(/\.pptx$/i, '') : '') || 'Untitled presentation'
}

export function presentationStatusLabel(status: string): string {
  const normalized = status.trim().toUpperCase()
  if (normalized === 'SUCCESS') return 'Ready'
  if (normalized === 'FAILED') return 'Failed'
  if (normalized === 'INIT') return 'Starting'
  if (normalized === 'REQUIREMENT') return 'Clarifying'
  if (normalized === 'SEARCH') return 'Researching'
  if (normalized === 'OUTLINE') return 'Outlining'
  if (normalized === 'TEMPLATE') return 'Choosing template'
  if (normalized === 'SCHEMA') return 'Designing slides'
  if (normalized === 'RENDER') return 'Rendering'
  return status.trim() || 'Unknown'
}

export function presentationStatusTone(status: string): PresentationStatusTone {
  const normalized = status.trim().toUpperCase()
  if (normalized === 'SUCCESS') return 'ready'
  if (normalized === 'FAILED') return 'failed'
  return 'active'
}

export function presentationLibraryItems(
  items: PresentationInfo[],
  query = '',
): PresentationInfo[] {
  const needle = query.trim().toLowerCase()
  return [...items]
    .filter((item) => {
      if (!needle) return true
      return [
        presentationTitle(item),
        presentationFileName(item),
        item.conversationId || '',
        presentationStatusLabel(item.status),
      ].some((value) => value.toLowerCase().includes(needle))
    })
    .sort((a, b) => timestamp(b) - timestamp(a) || b.id - a.id)
}
