import { expect, test, type Page } from '@playwright/test'

const emptySessions = {
  code: 200,
  message: 'success',
  data: {
    pageNum: 1,
    pageSize: 100,
    total: 0,
    records: [],
  },
}

function sse(events: Array<Record<string, unknown>>): string {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('')
}

async function mockHistory(page: Page) {
  await page.route('**/api/session/list**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(emptySessions),
    })
  })
}

async function mockChat(page: Page, events: Array<Record<string, unknown>>) {
  await page.route('**/api/agent/chat/stream**', async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        'content-type': 'text/event-stream; charset=utf-8',
        'cache-control': 'no-cache',
      },
      body: sse(events),
    })
  })
}

async function mockSkills(
  page: Page,
  events: Array<Record<string, unknown>>,
  onRequest?: (url: URL) => void,
) {
  await page.route('**/api/agent/skills/stream**', async (route) => {
    onRequest?.(new URL(route.request().url()))
    await route.fulfill({
      status: 200,
      headers: {
        'content-type': 'text/event-stream; charset=utf-8',
        'cache-control': 'no-cache',
      },
      body: sse(events),
    })
  })
}

async function openHome(page: Page) {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'What can I help with?' })).toBeVisible()
}

async function send(page: Page, message: string) {
  const composer = page.getByRole('textbox', { name: 'Message' })
  await composer.fill(message)
  await composer.press('Enter')
}

test.beforeEach(async ({ page }) => {
  await mockHistory(page)
})

test('Agent modes visibly differentiate the empty workspace before a message is sent', async ({ page }) => {
  await openHome(page)

  const composer = page.getByRole('textbox', { name: 'Message' })
  await expect(composer).toHaveAttribute('placeholder', /Ask a question, explore an idea/i)

  await page.getByRole('group', { name: 'Agent mode' }).getByRole('button', { name: 'Research', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Research a complex question' })).toBeVisible()
  await expect(page.getByText(/Uses multiple sources and returns a researched answer with citations/i)).toBeVisible()
  await expect(composer).toHaveAttribute('placeholder', /researched, compared, or verified/i)

  await page.getByRole('button', { name: 'File', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Work with a file' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Attach or choose file' })).toBeVisible()
  await expect(composer).toHaveAttribute('placeholder', /attached file/i)

  await page.getByRole('button', { name: 'Skills', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Put tools to work' })).toBeVisible()
  await expect(page.getByText(/Use tools and skills when the task needs more than a direct answer/i)).toBeVisible()
  await expect(composer).toHaveAttribute('placeholder', /choose the right tools/i)

  await page.getByRole('button', { name: 'PPT', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Build a presentation' })).toBeVisible()
  await expect(page.getByText(/Describe the audience, purpose, and slide count you want/i)).toBeVisible()
  await expect(composer).toHaveAttribute('placeholder', /topic, audience, slide count/i)
})

test('switching mode after a completed turn starts a fresh conversation and reload restores that mode', async ({ page }) => {
  let chatConversationId = ''
  let researchConversationId = ''

  await page.route('**/api/agent/chat/stream**', async (route) => {
    chatConversationId = new URL(route.request().url()).searchParams.get('conversationId') || ''
    await route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream; charset=utf-8' },
      body: sse([{ type: 'text', content: 'Chat conversation answer.' }, { type: 'complete' }]),
    })
  })
  await page.route('**/api/agent/deep/stream**', async (route) => {
    researchConversationId = new URL(route.request().url()).searchParams.get('conversationId') || ''
    await route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream; charset=utf-8' },
      body: sse([{ type: 'text', content: 'Research conversation answer.' }, { type: 'complete' }]),
    })
  })

  await openHome(page)
  await send(page, 'Start in Chat')
  await expect(page.getByText('Chat conversation answer.', { exact: true })).toBeVisible()
  await expect(page).toHaveURL(/\/c\/.+/)

  await page.getByRole('group', { name: 'Agent mode' }).getByRole('button', { name: 'Research', exact: true }).click()

  await expect(page).toHaveURL('/')
  await expect(page.getByRole('heading', { name: 'Research a complex question' })).toBeVisible()
  await expect(page.getByText('Chat conversation answer.', { exact: true })).toBeHidden()

  await send(page, 'Continue as research')
  await expect(page.getByText('Research conversation answer.', { exact: true })).toBeVisible()
  expect(chatConversationId).not.toBe('')
  expect(researchConversationId).not.toBe('')
  expect(researchConversationId).not.toBe(chatConversationId)

  await page.route(`**/api/session/${researchConversationId}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
        message: 'success',
        data: {
          conversationId: researchConversationId,
          agentType: 'plan-execute',
          fileid: null,
          messages: [
            {
              id: 21,
              question: 'Continue as research',
              answer: 'Research conversation answer.',
              createTime: '2026-08-28T21:00:00',
            },
          ],
        },
      }),
    })
  })

  await page.reload()

  await expect(
    page.getByRole('group', { name: 'Agent mode' }).getByRole('button', { name: 'Research', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByText('Research conversation answer.', { exact: true })).toBeVisible()
})

test('Chat smoke: Enter sends and the canonical SSE sequence reaches complete UI', async ({ page }) => {
  await mockChat(page, [
    { type: 'thinking', content: 'Inspecting the request…' },
    { type: 'text', content: 'Browser E2E answer.' },
    { type: 'recommend', content: ['Ask a follow-up'], count: 1 },
    { type: 'complete' },
  ])
  await openHome(page)

  await send(page, 'Run browser smoke')

  await expect(page.getByText('Run browser smoke', { exact: true })).toBeVisible()
  await expect(page.getByText('Thinking', { exact: true })).toBeVisible()
  await expect(page.getByText('Browser E2E answer.', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Regenerate response' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Send message', exact: true })).toBeVisible()
})

test('Stop: aborts an in-flight request and leaves a stable stopped state', async ({ page }) => {
  await page.route('**/api/agent/chat/stream**', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 5_000))
    try {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream; charset=utf-8' },
        body: sse([
          { type: 'thinking', content: 'Still working…' },
          { type: 'text', content: 'This should not replace the stopped state.' },
          { type: 'complete' },
        ]),
      })
    } catch {
      // The browser intentionally aborts this request after Stop.
    }
  })
  await page.route('**/api/agent/stop**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, message: 'stopped' }),
    })
  })
  await openHome(page)

  await send(page, 'Generate a long answer')
  const stop = page.getByRole('button', { name: 'Stop generating' })
  await expect(stop).toBeVisible()
  await stop.click()

  await expect(page.getByText('Generation stopped.', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Send message', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Regenerate response' })).toBeVisible()
})

test('Tool + Sources: tool completion and clickable references render from SSE', async ({ page }) => {
  await mockChat(page, [
    { type: 'thinking', content: 'Searching documentation…' },
    {
      type: 'tool_start',
      toolName: 'web_search',
      toolCallId: 'web-1',
      arguments: '{"query":"FastAPI docs"}',
    },
    {
      type: 'tool_end',
      toolName: 'web_search',
      toolCallId: 'web-1',
      result: '{"results":1}',
    },
    { type: 'text', content: 'The search completed successfully.' },
    {
      type: 'reference',
      content: [
        {
          title: 'FastAPI documentation',
          url: 'https://fastapi.tiangolo.com/',
          content: 'Official docs',
        },
      ],
      count: 1,
    },
    { type: 'complete' },
  ])
  await openHome(page)

  await send(page, 'Search FastAPI documentation')

  const activity = page.getByLabel('Agent activity')
  await expect(activity).toBeVisible()
  await expect(activity.locator('summary').first()).toContainText(/searching the web/i)
  await expect(page.getByRole('heading', { name: 'Sources' })).toBeVisible()

  const source = page.getByRole('link', { name: /FastAPI documentation/i })
  await expect(source).toBeVisible()
  await expect(source).toHaveAttribute('href', 'https://fastapi.tiangolo.com/')
  await expect(source).toHaveAttribute('target', '_blank')
})

test('Skills without a file sends successfully and preserves tool parameters, results, retry, errors, and order', async ({ page }) => {
  let requestedFileId: string | null | undefined
  await mockSkills(
    page,
    [
      { type: 'thinking', content: 'Selecting tools…' },
      { type: 'error', code: 'LLM_CALL_FAILED', message: 'LLM call failed, retrying (1/2)', detail: 'temporary' },
      {
        type: 'tool_start',
        toolName: 'read_skill',
        toolCallId: 'skill-1',
        arguments: '{"skill":"code-review"}',
      },
      {
        type: 'tool_start',
        toolName: 'grep',
        toolCallId: 'grep-1',
        arguments: '{"pattern":"TODO","path":"."}',
      },
      {
        type: 'tool_start',
        toolName: 'bash',
        toolCallId: 'bash-1',
        arguments: '{"command":"python -c pass"}',
      },
      { type: 'tool_end', toolName: 'grep', toolCallId: 'grep-1', result: 'src/app.ts:4:TODO' },
      { type: 'tool_end', toolName: 'bash', toolCallId: 'bash-1', result: 'Error: 命令不在允许列表' },
      {
        type: 'tool_end',
        toolName: 'read_skill',
        toolCallId: 'skill-1',
        result: '{"success":true,"skill":"code-review"}',
      },
      { type: 'text', content: 'Skills completed.' },
      { type: 'complete' },
    ],
    (url) => {
      requestedFileId = url.searchParams.get('fileId')
    },
  )
  await openHome(page)

  await page.getByRole('button', { name: 'Skills', exact: true }).click()
  await send(page, 'Inspect the workspace with the right tools')

  expect(requestedFileId).toBeNull()
  await expect(page.getByText('Skills completed.', { exact: true })).toBeVisible()

  const activity = page.getByLabel('Agent activity')
  const toolRows = activity.locator('details').filter({ has: page.locator('summary') })
  await expect(activity.locator('summary').nth(0)).toContainText(/reading skill instructions/i)
  await expect(activity.locator('summary').nth(1)).toContainText(/searching workspace text/i)
  await expect(activity.locator('summary').nth(2)).toContainText(/running an allowed command/i)
  await expect(activity.locator('summary').nth(2)).toContainText('Failed')
  await expect(activity.getByText('LLM call failed, retrying (1/2)', { exact: true })).toBeVisible()

  await activity.locator('summary').nth(0).click()
  await expect(activity.locator('details').nth(0)).toContainText('Parameters')
  await expect(activity.locator('details').nth(0)).toContainText('"skill": "code-review"')
  await expect(activity.locator('details').nth(0)).toContainText('Result')
  await expect(activity.locator('details').nth(0)).toContainText('"success": true')

  await activity.locator('summary').nth(1).click()
  await expect(activity.locator('details').nth(1)).toContainText('src/app.ts:4:TODO')
  await expect(toolRows).toHaveCount(4)
})

test('Skills with an uploaded file forwards fileId and renders File Content activity', async ({ page }) => {
  let requestedFileId: string | null | undefined
  await page.route('**/api/file/upload', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
        message: 'success',
        data: {
          fileId: 'skills-file-1',
          fileName: 'skills-notes.txt',
          fileType: 'txt',
          fileSize: 17,
          status: 'SUCCESS',
        },
      }),
    })
  })
  await mockSkills(
    page,
    [
      {
        type: 'tool_start',
        toolName: 'loadContent',
        toolCallId: 'file-1',
        arguments: '{"fileId":"skills-file-1","question":"summarize"}',
      },
      {
        type: 'tool_end',
        toolName: 'loadContent',
        toolCallId: 'file-1',
        result: '=== 文件内容 ===\\nimportant notes',
      },
      { type: 'text', content: 'File-aware Skills answer.' },
      { type: 'complete' },
    ],
    (url) => {
      requestedFileId = url.searchParams.get('fileId')
    },
  )
  await openHome(page)

  await page.getByRole('button', { name: 'Skills', exact: true }).click()
  await page.getByLabel('Choose a new file').setInputFiles({
    name: 'skills-notes.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('important notes'),
  })
  await expect(page.getByText('skills-notes.txt', { exact: true })).toBeVisible()

  await send(page, 'Summarize the attachment with Skills')

  expect(requestedFileId).toBe('skills-file-1')
  await expect(page.getByText('File-aware Skills answer.', { exact: true })).toBeVisible()
  const activity = page.getByLabel('Agent activity')
  await expect(activity.locator('summary').first()).toContainText(/reading uploaded file/i)
})

test('restored Skills history keeps Skills mode and persisted tool names', async ({ page }) => {
  await page.route('**/api/session/skills-history', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
        message: 'success',
        data: {
          conversationId: 'skills-history',
          agentType: 'skills',
          fileid: null,
          messages: [
            {
              id: 31,
              question: 'Inspect the workspace',
              answer: 'Historical Skills answer.',
              tools: 'read_skill,grep,bash',
              createTime: '2026-08-29T08:00:00',
            },
          ],
        },
      }),
    })
  })

  await page.goto('/c/skills-history')

  await expect(page.getByRole('button', { name: 'Skills', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByText('Historical Skills answer.', { exact: true })).toBeVisible()
  const activity = page.getByLabel('Agent activity')
  await expect(activity.locator('summary').nth(0)).toContainText(/reading skill instructions/i)
  await expect(activity.locator('summary').nth(1)).toContainText(/searching workspace text/i)
  await expect(activity.locator('summary').nth(2)).toContainText(/running an allowed command/i)
})

test('Research history is a real workspace route and restores final report with sources', async ({ page }) => {
  await page.route('**/api/session/list**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
        message: 'success',
        data: {
          pageNum: 1,
          pageSize: 100,
          total: 4,
          records: [
            {
              conversationId: 'chat-history',
              agentType: 'websearch',
              question: 'General chat history',
              answer: 'Chat answer',
              updateTime: '2026-08-29T08:00:00',
            },
            {
              conversationId: 'research-history-1',
              agentType: 'plan-execute',
              question: 'Compare agent memory strategies',
              answer: '# Research report',
              updateTime: '2026-08-29T09:15:00',
            },
            {
              conversationId: 'research-history-2',
              agentType: 'plan-execute',
              question: 'Investigate evaluation frameworks',
              answer: null,
              updateTime: '2026-08-29T09:00:00',
            },
            {
              conversationId: 'ppt-history',
              agentType: 'pptx',
              question: 'Build a presentation',
              answer: 'Deck ready',
              updateTime: '2026-08-29T07:30:00',
            },
          ],
        },
      }),
    })
  })

  await page.route('**/api/session/research-history-1', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
        message: 'success',
        data: {
          conversationId: 'research-history-1',
          agentType: 'plan-execute',
          fileid: null,
          messages: [
            {
              id: 51,
              question: 'Compare agent memory strategies',
              answer: '# Research report\n\nLong-term memory should be evaluated against retrieval quality.',
              thinking: 'Research plan complete.',
              reference: JSON.stringify({
                type: 'reference',
                content: JSON.stringify([
                  {
                    title: 'Memory systems paper',
                    url: 'https://example.com/memory-paper',
                    content: 'Primary research source',
                  },
                  {
                    title: 'Evaluation guide',
                    url: 'https://example.org/evaluation-guide',
                    content: 'Evaluation criteria',
                  },
                ]),
                count: 2,
              }),
              createTime: '2026-08-29T09:15:00',
            },
          ],
        },
      }),
    })
  })

  await openHome(page)
  const workspace = page.getByRole('navigation', { name: 'Workspace' })
  await workspace.getByRole('button', { name: 'Research', exact: true }).click()

  await expect(page).toHaveURL('/research')
  await expect(page.getByRole('heading', { name: 'Research history' })).toBeVisible()
  const memoryResearch = page.getByRole('button', { name: 'Open research: Compare agent memory strategies' })
  const evaluationResearch = page.getByRole('button', { name: 'Open research: Investigate evaluation frameworks' })
  await expect(memoryResearch).toBeVisible()
  await expect(evaluationResearch).toBeVisible()
  await expect(page.getByText('General chat history', { exact: true })).toBeHidden()
  await expect(page.getByText('Build a presentation', { exact: true })).toBeHidden()
  await expect(page.getByText('Complete', { exact: true })).toBeVisible()
  await expect(page.getByText('In progress', { exact: true })).toBeVisible()

  const search = page.getByRole('searchbox', { name: 'Search research history' })
  await search.fill('evaluation')
  await expect(evaluationResearch).toBeVisible()
  await expect(memoryResearch).toBeHidden()
  await search.fill('')

  await memoryResearch.click()

  await expect(page).toHaveURL('/c/research-history-1')
  await expect(
    page.getByRole('group', { name: 'Agent mode' }).getByRole('button', { name: 'Research', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByText('Final report', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Research report' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Sources' })).toBeVisible()
  await expect(page.getByRole('link', { name: /Memory systems paper/i })).toHaveAttribute(
    'href',
    'https://example.com/memory-paper',
  )
  await expect(page.getByRole('link', { name: /Evaluation guide/i })).toHaveAttribute(
    'href',
    'https://example.org/evaluation-guide',
  )
})

test('Presentations workspace lists real PPT assets and supports open, download, continue editing, and delete', async ({ page }) => {
  await page.route('**/api/session/list**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
        message: 'success',
        data: {
          pageNum: 1,
          pageSize: 100,
          total: 2,
          records: [
            {
              conversationId: 'ppt-history',
              agentType: 'pptx',
              question: 'AI interview walkthrough',
              answer: 'Deck ready',
              updateTime: '2026-08-29T09:30:00',
            },
            {
              conversationId: 'ppt-failed',
              agentType: 'pptx',
              question: 'Failed architecture deck',
              answer: null,
              updateTime: '2026-08-29T09:10:00',
            },
          ],
        },
      }),
    })
  })

  await page.route('**/api/ppt/list', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
        message: 'success',
        data: {
          count: 2,
          presentations: [
            {
              id: 7,
              conversationId: 'ppt-history',
              status: 'SUCCESS',
              query: 'AI interview walkthrough',
              fileUrl: 'https://files.example/ppt/ppt-history/ppt_7_demo.pptx',
              createTime: '2026-08-29T09:20:00',
              updateTime: '2026-08-29T09:30:00',
            },
            {
              id: 8,
              conversationId: 'ppt-failed',
              status: 'FAILED',
              query: 'Failed architecture deck',
              errorMsg: 'render failed',
              createTime: '2026-08-29T09:00:00',
              updateTime: '2026-08-29T09:10:00',
            },
          ],
        },
      }),
    })
  })

  await page.route('**/api/session/ppt-history', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
        message: 'success',
        data: {
          conversationId: 'ppt-history',
          agentType: 'pptx',
          fileid: null,
          messages: [
            {
              id: 71,
              question: 'AI interview walkthrough',
              answer: 'PPT已生成：https://files.example/ppt/ppt-history/ppt_7_demo.pptx',
              thinking: '开始创建新的PPT...\n正在渲染PPT...\n✅ PPT渲染完成',
              createTime: '2026-08-29T09:30:00',
            },
          ],
        },
      }),
    })
  })

  let deletedId = ''
  await page.route('**/api/ppt/8', async (route) => {
    deletedId = route.request().url().split('/').pop() || ''
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 200, message: 'PPT删除成功', data: null }),
    })
  })

  await openHome(page)
  const workspace = page.getByRole('navigation', { name: 'Workspace' })
  await workspace.getByRole('button', { name: 'Presentations', exact: true }).click()

  await expect(page).toHaveURL('/presentations')
  await expect(page.getByRole('heading', { name: 'Presentations' })).toBeVisible()

  const readyCard = page.getByRole('article').filter({ hasText: 'AI interview walkthrough' })
  const failedCard = page.getByRole('article').filter({ hasText: 'Failed architecture deck' })
  await expect(readyCard).toBeVisible()
  await expect(failedCard).toBeVisible()
  await expect(readyCard.getByText('Ready', { exact: true })).toBeVisible()
  await expect(failedCard.getByText('Failed', { exact: true })).toBeVisible()
  await expect(failedCard.getByText('render failed', { exact: true })).toBeVisible()

  const open = readyCard.getByRole('link', { name: 'Open', exact: true })
  await expect(open).toHaveAttribute('href', 'https://files.example/ppt/ppt-history/ppt_7_demo.pptx')
  await expect(open).toHaveAttribute('target', '_blank')
  const download = readyCard.getByRole('link', { name: 'Download', exact: true })
  await expect(download).toHaveAttribute('href', 'https://files.example/ppt/ppt-history/ppt_7_demo.pptx')
  await expect(download).toHaveAttribute('download', 'ppt_7_demo.pptx')

  page.once('dialog', (dialog) => dialog.accept())
  await failedCard.getByRole('button', { name: 'Delete presentation: Failed architecture deck' }).click()
  await expect(failedCard).toBeHidden()
  expect(deletedId).toBe('8')

  await readyCard.getByRole('button', { name: 'Continue editing' }).click()
  await expect(page).toHaveURL('/c/ppt-history')
  await expect(
    page.getByRole('group', { name: 'Agent mode' }).getByRole('button', { name: 'PPT', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByLabel('Presentation file').getByText('Presentation ready', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open PPT' })).toHaveAttribute(
    'href',
    'https://files.example/ppt/ppt-history/ppt_7_demo.pptx',
  )
})

const responsiveCases = [
  { name: '1440px', width: 1440, height: 900 },
  { name: '1024px', width: 1024, height: 800 },
  { name: '768px', width: 768, height: 900 },
  { name: '390px', width: 390, height: 844 },
]

for (const viewport of responsiveCases) {
  test(`Responsive ${viewport.name}: no body overflow and conversation controls remain usable`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    const longLine = `const payload = "${'x'.repeat(320)}"`
    await mockChat(page, [
      { type: 'thinking', content: 'Checking responsive layout…' },
      {
        type: 'text',
        content: `Responsive answer.\n\n\`\`\`typescript\n${longLine}\n\`\`\``,
      },
      {
        type: 'reference',
        content: Array.from({ length: 6 }, (_, index) => ({
          title: `Responsive source ${index + 1}`,
          url: `https://example.com/source-${index + 1}`,
        })),
        count: 6,
      },
      { type: 'complete' },
    ])
    await openHome(page)

    if (viewport.width < 768) {
      const openSidebar = page.getByRole('button', { name: 'Open sidebar' })
      const openBox = await openSidebar.boundingBox()
      expect(openBox?.width).toBeGreaterThanOrEqual(44)
      expect(openBox?.height).toBeGreaterThanOrEqual(44)
      await openSidebar.click()
      const mobileNavigation = page.getByRole('dialog', { name: 'Mobile navigation' })
      const mobileSidebar = mobileNavigation.getByRole('complementary', { name: 'DeepDesk workspace sidebar' })
      await expect(mobileSidebar).toBeVisible()
      await mobileSidebar.getByRole('button', { name: 'Close sidebar' }).click()
      await expect(mobileNavigation).toBeHidden()
    }

    await send(page, `Responsive smoke ${viewport.name}`)
    await expect(page.getByText('Responsive answer.', { exact: true })).toBeVisible()

    const dimensions = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      document: document.documentElement.scrollWidth,
    }))
    expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport)

    const pre = page.locator('.code-block pre').first()
    await expect(pre).toBeVisible()
    expect(await pre.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true)

    const scrollViewport = page.locator('div.h-full.overflow-y-auto').first()
    const composer = page.getByRole('textbox', { name: 'Message' })
    const scrollBox = await scrollViewport.boundingBox()
    const composerBox = await composer.boundingBox()
    expect(scrollBox).not.toBeNull()
    expect(composerBox).not.toBeNull()
    expect((scrollBox?.y ?? 0) + (scrollBox?.height ?? 0)).toBeLessThanOrEqual((composerBox?.y ?? 0) + 1)

    const sources = page.getByRole('link', { name: /Responsive source/ })
    await expect(sources).toHaveCount(6)
    const sourcesWithinViewport = await sources.evaluateAll((links) =>
      links.every((link) => {
        const rect = link.getBoundingClientRect()
        return rect.left >= -1 && rect.right <= document.documentElement.clientWidth + 1
      }),
    )
    expect(sourcesWithinViewport).toBe(true)

    if (viewport.width === 390) {
      const sendControl = page.getByRole('button', { name: 'Send message', exact: true })
      const sendBox = await sendControl.boundingBox()
      expect(sendBox?.width).toBeGreaterThanOrEqual(44)
      expect(sendBox?.height).toBeGreaterThanOrEqual(44)
    }
  })
}

test('Theme: Light, Dark, and System persist across refresh', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 800 })
  await openHome(page)

  const openSettings = async () => {
    await page.getByRole('button', { name: 'Settings' }).click()
    await expect(page.getByRole('dialog', { name: 'Settings' })).toBeVisible()
  }

  await openSettings()
  await page.getByRole('button', { name: 'Dark' }).click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  expect(await page.evaluate(() => localStorage.getItem('deepdesk.theme'))).toBe('dark')

  await page.reload()
  await expect(page.locator('html')).toHaveClass(/dark/)

  await openSettings()
  await page.getByRole('button', { name: 'Light' }).click()
  await expect(page.locator('html')).not.toHaveClass(/dark/)
  expect(await page.evaluate(() => localStorage.getItem('deepdesk.theme'))).toBe('light')

  await page.reload()
  await expect(page.locator('html')).not.toHaveClass(/dark/)

  await page.emulateMedia({ colorScheme: 'dark' })
  await openSettings()
  await page.getByRole('button', { name: 'System' }).click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  expect(await page.evaluate(() => localStorage.getItem('deepdesk.theme'))).toBe('system')

  await page.reload()
  await expect(page.locator('html')).toHaveClass(/dark/)
})
