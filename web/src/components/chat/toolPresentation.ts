import type { StreamError } from '../../types/agent'

const TOOL_LABELS: Record<string, string> = {
  web_search: 'Searching the web',
  loadcontent: 'Reading uploaded file',
  read_skill: 'Reading skill instructions',
  read_file: 'Reading workspace file',
  write_file: 'Creating workspace file',
  edit_file: 'Editing workspace file',
  glob_files: 'Finding workspace files',
  list_files: 'Listing workspace files',
  grep: 'Searching workspace text',
  bash: 'Running an allowed command',
}

export function toolLabel(name: string): string {
  const key = name.trim().toLowerCase()
  if (TOOL_LABELS[key]) return TOOL_LABELS[key]
  if (key.includes('search')) return 'Searching the web'
  if (key.includes('filecontent') || key.includes('file_content') || key.includes('loadcontent')) {
    return 'Reading uploaded file'
  }
  if (key.includes('read_skill')) return 'Reading skill instructions'
  if (key.includes('skill')) return 'Using a skill'
  if (key.includes('grep')) return 'Searching workspace text'
  if (key.includes('filesystem')) return 'Reading workspace files'
  if (key.includes('bash')) return 'Running an allowed command'
  return name.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export function prettyToolValue(value: unknown): string {
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed) return value
    try {
      const parsed = JSON.parse(trimmed) as unknown
      if (parsed !== null && typeof parsed === 'object') return JSON.stringify(parsed, null, 2)
    } catch {
      // Tool results are often plain text, so non-JSON strings should remain unchanged.
    }
    return value
  }
  if (value === undefined) return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function isTransientRetry(error: StreamError): boolean {
  return error.transient === true
}
