import type { AgentDefinition, AgentMode } from '../types/agent'

export const AGENTS: AgentDefinition[] = [
  {
    id: 'chat',
    label: 'Chat',
    shortLabel: 'Ask',
    description: 'Ask, search, and think through a question.',
  },
  {
    id: 'research',
    label: 'Deep Research',
    shortLabel: 'Research',
    description: 'Build a researched answer with sources.',
  },
  {
    id: 'file',
    label: 'File',
    shortLabel: 'File',
    description: 'Upload one file and ask questions about it.',
  },
  {
    id: 'skills',
    label: 'Skills',
    shortLabel: 'Skills',
    description: 'Use the available tools and skills for a task.',
  },
  {
    id: 'ppt',
    label: 'PPT',
    shortLabel: 'PPT',
    description: 'Create or continue a presentation.',
  },
]

export const AGENT_BY_ID = Object.fromEntries(AGENTS.map((agent) => [agent.id, agent])) as Record<
  AgentMode,
  AgentDefinition
>

export const BACKEND_AGENT_TO_MODE: Record<string, AgentMode> = {
  websearch: 'chat',
  file: 'file',
  skills: 'skills',
  'plan-execute': 'research',
  pptx: 'ppt',
}

export function modeFromBackend(agentType?: string | null): AgentMode {
  if (!agentType) return 'chat'
  return BACKEND_AGENT_TO_MODE[agentType] ?? 'chat'
}
