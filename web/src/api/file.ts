import type { BaseResult, FileContent, FileInfo, FileList } from '../types/api'
import { ApiError, apiUrl, authHeaders, requestJson, requestResult } from './client'

export interface UploadHandle {
  promise: Promise<FileInfo>
  abort: () => void
}

export function uploadFile(
  file: File,
  onProgress?: (progress: number) => void,
  onUploadComplete?: () => void,
): UploadHandle {
  const xhr = new XMLHttpRequest()
  const form = new FormData()
  form.append('file', file)

  const promise = new Promise<FileInfo>((resolve, reject) => {
    xhr.open('POST', apiUrl('/file/upload'))
    xhr.setRequestHeader('Accept', 'application/json')
    for (const [key, value] of Object.entries(authHeaders())) xhr.setRequestHeader(key, value)

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) onProgress?.(Math.round((event.loaded / event.total) * 100))
    })
    xhr.upload.addEventListener('load', () => onUploadComplete?.())

    xhr.addEventListener('load', () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(`Upload failed with HTTP ${xhr.status}`))
        return
      }
      try {
        const result = JSON.parse(xhr.responseText) as BaseResult<FileInfo>
        if (result.code !== 200 || !result.data) {
          reject(new ApiError(result.message || 'File upload failed.', { code: result.code }))
          return
        }
        onProgress?.(100)
        resolve(result.data)
      } catch {
        reject(new Error('The upload response could not be read.'))
      }
    })

    xhr.addEventListener('error', () => reject(new Error('Unable to reach the file service.')))
    xhr.addEventListener('abort', () => reject(new DOMException('Upload cancelled', 'AbortError')))
    xhr.send(form)
  })

  return { promise, abort: () => xhr.abort() }
}

export function getFileInfo(fileId: string): Promise<FileInfo> {
  return requestResult<FileInfo>(`/file/info/${encodeURIComponent(fileId)}`, { method: 'GET' })
}

export function getFileContent(fileId: string): Promise<FileContent> {
  return requestResult<FileContent>(`/file/content/${encodeURIComponent(fileId)}`, { method: 'GET' })
}

export function listFiles(): Promise<FileList> {
  return requestResult<FileList>('/file/list', { method: 'GET' })
}

export function fileExists(fileId: string): Promise<boolean> {
  return requestResult<boolean>(`/file/exists/${encodeURIComponent(fileId)}`, { method: 'GET' })
}

export async function deleteFile(fileId: string): Promise<string> {
  const result = await requestJson<BaseResult<string>>(`/file/${encodeURIComponent(fileId)}`, {
    method: 'DELETE',
  })
  if (result.code !== 200) throw new Error(result.message || 'Unable to delete file.')
  return result.message
}
