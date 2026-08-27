import { expect, test, type Locator, type Page } from '@playwright/test'

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
      headers: { 'content-type': 'text/event-stream; charset=utf-8' },
      body: sse(events),
    })
  })
}

async function openHome(page: Page) {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'What can I help with?' })).toBeVisible()
}

async function tabUntil(page: Page, target: Locator, maxTabs = 60) {
  await page.evaluate(() => {
    const active = document.activeElement
    if (active instanceof HTMLElement) active.blur()
  })

  for (let index = 0; index < maxTabs; index += 1) {
    await page.keyboard.press('Tab')
    if (await target.evaluate((element) => element === document.activeElement)) return
  }
  throw new Error(`Target was not keyboard reachable within ${maxTabs} Tab presses.`)
}

async function expectModalKeyboardContainment(page: Page, dialog: Locator, tabCount = 10) {
  for (let index = 0; index < tabCount; index += 1) {
    await page.keyboard.press('Tab')
    const focusLocation = await dialog.evaluate((element) => {
      const active = document.activeElement
      if (element.contains(active)) return 'inside'
      if (active === document.body) return 'body-boundary'
      return 'outside'
    })
    expect(focusLocation).not.toBe('outside')
  }
}

function parseColor(value: string): [number, number, number] {
  const hex = value.match(/^#([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i)
  if (hex) return [Number.parseInt(hex[1], 16), Number.parseInt(hex[2], 16), Number.parseInt(hex[3], 16)]

  const rgb = value.match(/rgba?\((\d+(?:\.\d+)?)\s*[ ,]\s*(\d+(?:\.\d+)?)\s*[ ,]\s*(\d+(?:\.\d+)?)/)
  if (!rgb) throw new Error(`Unsupported color: ${value}`)
  return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])]
}

function luminance([red, green, blue]: [number, number, number]): number {
  const channel = (value: number) => {
    const normalized = value / 255
    return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)
}

function contrast(foreground: [number, number, number], background: [number, number, number]): number {
  const first = luminance(foreground)
  const second = luminance(background)
  const lighter = Math.max(first, second)
  const darker = Math.min(first, second)
  return (lighter + 0.05) / (darker + 0.05)
}

test.beforeEach(async ({ page }) => {
  await mockHistory(page)
})

test('keyboard reaches sidebar, mode selector, composer, tool details, and sources with visible focus', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 800 })
  await mockChat(page, [
    { type: 'thinking', content: 'Checking keyboard access…' },
    {
      type: 'tool_start',
      toolName: 'web_search',
      toolCallId: 'a11y-tool',
      arguments: '{"query":"accessibility"}',
    },
    {
      type: 'tool_end',
      toolName: 'web_search',
      toolCallId: 'a11y-tool',
      result: '{"ok":true}',
    },
    { type: 'text', content: 'Keyboard-accessible response.' },
    {
      type: 'reference',
      content: [{ title: 'Accessibility source', url: 'https://example.com/accessibility' }],
      count: 1,
    },
    { type: 'complete' },
  ])
  await openHome(page)

  const collapse = page.getByRole('button', { name: 'Collapse sidebar' })
  await tabUntil(page, collapse)
  await expect(collapse).toBeFocused()

  const chatMode = page.getByRole('button', { name: 'Chat', exact: true })
  const researchMode = page.getByRole('button', { name: 'Deep Research', exact: true })
  await expect(chatMode).toHaveAttribute('aria-pressed', 'true')
  await tabUntil(page, researchMode)
  await expect(researchMode).toBeFocused()
  const focusOutline = await researchMode.evaluate((element) => {
    const style = getComputedStyle(element)
    return { style: style.outlineStyle, width: Number.parseFloat(style.outlineWidth) }
  })
  expect(focusOutline.style).not.toBe('none')
  expect(focusOutline.width).toBeGreaterThanOrEqual(2)

  await researchMode.press('Enter')
  await expect(researchMode).toHaveAttribute('aria-pressed', 'true')
  await chatMode.focus()
  await chatMode.press('Enter')
  await expect(chatMode).toHaveAttribute('aria-pressed', 'true')

  const composer = page.getByRole('textbox', { name: 'Message' })
  const composerShell = composer.locator('..')
  const shadowBeforeFocus = await composerShell.evaluate((element) => getComputedStyle(element).boxShadow)
  await tabUntil(page, composer)
  await expect(composer).toBeFocused()
  const shadowAfterFocus = await composerShell.evaluate((element) => getComputedStyle(element).boxShadow)
  expect(shadowAfterFocus).not.toBe(shadowBeforeFocus)
  expect(await composer.evaluate((element) => getComputedStyle(element).outlineStyle)).toBe('none')

  await composer.fill('Run keyboard accessibility check')
  await composer.press('Enter')
  await expect(page.getByText('Keyboard-accessible response.', { exact: true })).toBeVisible()

  const toolSummary = page.getByLabel('Agent activity').locator('summary').first()
  await tabUntil(page, toolSummary)
  await expect(toolSummary).toBeFocused()
  await toolSummary.press('Enter')
  await expect(toolSummary.locator('..')).toHaveAttribute('open', '')

  const source = page.getByRole('link', { name: /Accessibility source/i })
  await tabUntil(page, source)
  await expect(source).toBeFocused()
  const sourceOutline = await source.evaluate((element) => {
    const style = getComputedStyle(element)
    return { style: style.outlineStyle, width: Number.parseFloat(style.outlineWidth) }
  })
  expect(sourceOutline.style).not.toBe('none')
  expect(sourceOutline.width).toBeGreaterThanOrEqual(2)
})

test('Settings native dialog traps focus, closes with Escape, and restores focus', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 800 })
  await openHome(page)

  const trigger = page.getByRole('button', { name: 'Settings' })
  await tabUntil(page, trigger)
  await trigger.press('Enter')

  const dialog = page.getByRole('dialog', { name: 'Settings' })
  await expect(dialog).toBeVisible()
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true)
  await expectModalKeyboardContainment(page, dialog)

  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
})

test('Mobile navigation is modal, keyboard-contained, Escape-dismissable, and restores its trigger', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openHome(page)

  const trigger = page.getByRole('button', { name: 'Open sidebar' })
  await tabUntil(page, trigger)
  await trigger.press('Enter')

  const dialog = page.getByRole('dialog', { name: 'Mobile navigation' })
  const sidebar = page.getByRole('complementary', { name: 'Conversation sidebar' })
  await expect(dialog).toBeVisible()
  await expect(sidebar).toBeVisible()
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true)
  await expectModalKeyboardContainment(page, dialog)

  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()

  await trigger.press('Enter')
  await expect(dialog).toBeVisible()
  const settingsTrigger = sidebar.getByRole('button', { name: 'Settings' })
  await settingsTrigger.focus()
  await settingsTrigger.press('Enter')

  const settingsDialog = page.getByRole('dialog', { name: 'Settings' })
  await expect(dialog).toBeHidden()
  await expect(settingsDialog).toBeVisible()
  expect(await settingsDialog.evaluate((element) => element.contains(document.activeElement))).toBe(true)

  await page.keyboard.press('Escape')
  await expect(settingsDialog).toBeHidden()
  await expect(trigger).toBeFocused()
})

test('streaming, completion, stopped, and terminal errors expose live status semantics', async ({ page }) => {
  await page.route('**/api/agent/chat/stream**', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 5_000))
    try {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream; charset=utf-8' },
        body: sse([{ type: 'text', content: 'Accessible status answer.' }, { type: 'complete' }]),
      })
    } catch {
      // The Stop branch intentionally aborts the request.
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

  const composer = page.getByRole('textbox', { name: 'Message' })
  await composer.fill('Check streaming status')
  await composer.press('Enter')
  await expect(page.getByRole('status', { name: '' }).filter({ hasText: 'Assistant response is streaming.' })).toBeVisible()

  await page.getByRole('button', { name: 'Stop generating' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Assistant response stopped.' })).toBeVisible()

  await page.unroute('**/api/agent/chat/stream**')
  await mockChat(page, [{ type: 'error', code: 'AGENT_ERROR', message: 'Provider unavailable' }, { type: 'complete' }])
  await composer.fill('Check error status')
  await composer.press('Enter')
  await expect(page.getByRole('alert').filter({ hasText: 'Generation failed.' })).toBeVisible()
})

test('reduced motion is honored and light/dark text tokens meet contrast floors', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.route('**/api/agent/chat/stream**', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 2_000))
    await route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream; charset=utf-8' },
      body: sse([{ type: 'thinking', content: 'Done.' }, { type: 'text', content: 'Done.' }, { type: 'complete' }]),
    })
  })
  await openHome(page)

  const composer = page.getByRole('textbox', { name: 'Message' })
  await composer.fill('Check reduced motion')
  await composer.press('Enter')

  const pulse = page.locator('.animate-pulse').first()
  await expect(pulse).toBeVisible()
  const animationDurationSeconds = await pulse.evaluate((element) => {
    const value = getComputedStyle(element).animationDuration.trim()
    if (value.endsWith('ms')) return Number.parseFloat(value) / 1000
    if (value.endsWith('s')) return Number.parseFloat(value)
    return Number.POSITIVE_INFINITY
  })
  expect(animationDurationSeconds).toBeLessThanOrEqual(0.00001)

  const lightRatios = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement)
    return {
      faint: [root.getPropertyValue('--ink-faint').trim(), root.getPropertyValue('--surface-muted').trim()],
      secondary: [root.getPropertyValue('--ink-secondary').trim(), root.getPropertyValue('--canvas').trim()],
      accent: [root.getPropertyValue('--accent').trim(), root.getPropertyValue('--canvas').trim()],
      focus: [root.getPropertyValue('--focus').trim(), root.getPropertyValue('--canvas').trim()],
    }
  })

  for (const [foreground, background] of Object.values(lightRatios)) {
    expect(contrast(parseColor(foreground), parseColor(background))).toBeGreaterThanOrEqual(4.5)
  }

  await page.evaluate(() => localStorage.setItem('deepdesk.theme', 'dark'))
  await page.reload()
  await expect(page.locator('html')).toHaveClass(/dark/)

  const darkRatios = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement)
    return {
      faint: [root.getPropertyValue('--ink-faint').trim(), root.getPropertyValue('--surface-muted').trim()],
      secondary: [root.getPropertyValue('--ink-secondary').trim(), root.getPropertyValue('--canvas').trim()],
      accent: [root.getPropertyValue('--accent').trim(), root.getPropertyValue('--canvas').trim()],
      focus: [root.getPropertyValue('--focus').trim(), root.getPropertyValue('--canvas').trim()],
    }
  })

  for (const [foreground, background] of Object.values(darkRatios)) {
    expect(contrast(parseColor(foreground), parseColor(background))).toBeGreaterThanOrEqual(4.5)
  }
})
