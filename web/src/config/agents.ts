import type { AgentDefinition, AgentMode } from '../types/agent'

export const AGENTS: AgentDefinition[] = [
  {
    id: 'chat',
    label: 'Chat',
    shortLabel: 'Ask',
    description: 'Ask, search, and think through a question.',
    headline: 'What can I help with?',
    placeholder: 'Ask a question, explore an idea, or work through a problem…',
    suggestions: [
      'Explain a difficult concept with a concrete example',
      'Compare two approaches and recommend one',
      'Help me turn rough notes into a clear plan',
    ],
    capabilities: ['Direct answers', 'Search when needed', 'Clear follow-up'],
  },
  {
    id: 'research',
    label: 'Deep Research',
    shortLabel: 'Research',
    description: 'Research complex topics across multiple sources and produce a structured report.',
    headline: 'Research a complex question',
    placeholder: 'Describe what you want researched, compared, or verified…',
    suggestions: [
      'Research the current landscape of AI coding agents and compare the leading approaches',
      'Investigate a technical topic across multiple sources and summarize the evidence',
      'Build a sourced report with key findings, trade-offs, and open questions',
    ],
    capabilities: ['Multi-source research', 'Plan and synthesize', 'Sources included'],
  },
  {
    id: 'file',
    label: 'File',
    shortLabel: 'File',
    description: 'Ask questions about PDFs, DOCX, text, and images.',
    headline: 'Work with a file',
    placeholder: 'Ask about the attached file, or leave this blank to analyze it…',
    suggestions: [
      'Summarize the key points and important details',
      'Extract decisions, action items, and open questions',
      'Find the sections most relevant to a specific topic',
    ],
    capabilities: ['PDF · DOCX · TXT', 'PNG · JPG · JPEG', 'Up to 50 MB'],
  },
  {
    id: 'skills',
    label: 'Skills',
    shortLabel: 'Skills',
    description: 'Let the agent discover and use tools to complete a task.',
    headline: 'Put tools to work',
    placeholder: 'Describe the task and let the agent choose the right tools…',
    suggestions: [
      'Search the web, inspect the results, and summarize what matters',
      'Read an available skill and use it to complete a task',
      'Inspect files and grep the workspace for the information I need',
    ],
    capabilities: ['Web Search', 'File Content', 'Read Skill', 'Grep', 'Filesystem', 'Restricted Bash'],
  },
  {
    id: 'ppt',
    label: 'PPT',
    shortLabel: 'PPT',
    description: 'Research, outline, and generate a presentation.',
    headline: 'Build a presentation',
    placeholder: 'Describe the topic, audience, slide count, and what the deck should achieve…',
    suggestions: [
      'Create a concise presentation for a technical interview walkthrough',
      'Turn a research topic into a structured 8-slide presentation',
      'Create a presentation, then help me revise its structure and content',
    ],
    capabilities: ['Research', 'Outline', 'Generate slides', 'Continue and modify'],
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
