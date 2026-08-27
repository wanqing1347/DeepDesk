import { describe, expect, it } from 'vitest'
import { isTransientRetry, prettyToolValue, toolLabel } from './toolPresentation'

describe('toolPresentation', () => {
  it('maps the real Skills Agent backend tool names to user-facing activity labels', () => {
    expect(toolLabel('read_skill')).toBe('Reading skill instructions')
    expect(toolLabel('web_search')).toBe('Searching the web')
    expect(toolLabel('loadContent')).toBe('Reading uploaded file')
    expect(toolLabel('read_file')).toBe('Reading workspace file')
    expect(toolLabel('write_file')).toBe('Creating workspace file')
    expect(toolLabel('edit_file')).toBe('Editing workspace file')
    expect(toolLabel('glob_files')).toBe('Finding workspace files')
    expect(toolLabel('list_files')).toBe('Listing workspace files')
    expect(toolLabel('grep')).toBe('Searching workspace text')
    expect(toolLabel('bash')).toBe('Running an allowed command')
  })

  it('pretty-prints JSON string payloads without altering plain text tool results', () => {
    expect(prettyToolValue('{"query":"FastAPI","limit":2}')).toContain('\n  "query": "FastAPI"')
    expect(prettyToolValue('notes.txt:2:needle here')).toBe('notes.txt:2:needle here')
  })

  it('only marks explicitly transient retry errors as retrying', () => {
    expect(isTransientRetry({ message: 'retry', transient: true })).toBe(true)
    expect(isTransientRetry({ message: 'failed' })).toBe(false)
  })
})
