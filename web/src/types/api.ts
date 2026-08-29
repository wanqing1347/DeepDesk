export interface BaseResult<T> {
  code: number
  message: string
  data: T | null
}

export interface PageResult<T> {
  pageNum: number
  pageSize: number
  total: number
  records: T[]
}

export interface SessionListItem {
  conversationId: string
  agentType?: string | null
  question?: string | null
  answer?: string | null
  messageCount?: number | null
  createTime?: string | null
  updateTime?: string | null
  fileid?: string | null
}

export interface StoredMessage {
  id: number
  question?: string | null
  answer?: string | null
  thinking?: string | null
  tools?: string | null
  reference?: string | null
  createTime?: string | null
  fileid?: string | null
  recommend?: string | null
}

export interface SessionDetail {
  conversationId: string
  agentType?: string | null
  fileid?: string | null
  messages: StoredMessage[]
}

export interface FileInfo {
  fileId: string
  fileName: string
  fileType?: string | null
  fileSize?: number | null
  minioPath?: string | null
  extractedText?: string | null
  createdAt?: string | null
  conversationId?: string | null
  status: string
  embed?: number | null
}

export interface FileList {
  count: number
  files: Record<string, FileInfo>
}

export interface FileContent {
  content: string
  length: number
}

export interface PresentationInfo {
  id: number
  conversationId?: string | null
  templateCode?: string | null
  status: string
  query?: string | null
  fileUrl?: string | null
  errorMsg?: string | null
  createTime?: string | null
  updateTime?: string | null
}

export interface PresentationList {
  count: number
  presentations: PresentationInfo[]
}

export interface StopResponse {
  success: boolean
  message: string
}
