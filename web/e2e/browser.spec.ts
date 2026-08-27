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
      const mobileSidebar = page.getByRole('complementary', { name: 'Conversation sidebar' })
      await expect(mobileSidebar).toBeVisible()
      await mobileSidebar.getByRole('button', { name: 'Close sidebar' }).click()
      await expect(mobileSidebar).toBeHidden()
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
      for (const control of [
        page.getByRole('button', { name: 'Attach file' }),
        page.getByRole('button', { name: 'Send message', exact: true }),
      ]) {
        const box = await control.boundingBox()
        expect(box?.width).toBeGreaterThanOrEqual(44)
        expect(box?.height).toBeGreaterThanOrEqual(44)
      }
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
