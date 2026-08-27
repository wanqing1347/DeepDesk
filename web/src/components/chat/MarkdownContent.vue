<script setup lang="ts">
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import python from 'highlight.js/lib/languages/python'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import { marked } from 'marked'
import { computed, nextTick, ref, watch } from 'vue'

hljs.registerLanguage('bash', bash)
hljs.registerLanguage('css', css)
hljs.registerLanguage('html', xml)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('js', javascript)
hljs.registerLanguage('json', json)
hljs.registerLanguage('python', python)
hljs.registerLanguage('py', python)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('ts', typescript)
hljs.registerLanguage('xml', xml)

const props = defineProps<{ content: string }>()
const root = ref<HTMLElement | null>(null)

marked.setOptions({ gfm: true, breaks: true })

const html = computed(() => {
  const rendered = marked.parse(props.content || '') as string
  return DOMPurify.sanitize(rendered, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'script', 'iframe', 'object', 'embed'],
  })
})

function codeLanguage(block: HTMLElement): string {
  const languageClass = [...block.classList].find((name) => name.startsWith('language-'))
  if (!languageClass) return 'code'
  return languageClass.slice('language-'.length) || 'code'
}

async function writeClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.append(textarea)
  textarea.select()
  document.execCommand('copy')
  textarea.remove()
}

function decorateCodeBlock(block: HTMLElement) {
  const pre = block.parentElement
  if (!pre || pre.tagName !== 'PRE' || pre.parentElement?.classList.contains('code-block')) return

  const wrapper = document.createElement('div')
  wrapper.className = 'code-block'
  const header = document.createElement('div')
  header.className = 'code-block-header'

  const language = document.createElement('span')
  language.className = 'code-block-language'
  language.textContent = codeLanguage(block)

  const copy = document.createElement('button')
  copy.type = 'button'
  copy.className = 'code-block-copy'
  copy.setAttribute('aria-label', `Copy ${language.textContent} code`)
  copy.textContent = 'Copy'

  const touchTarget = document.createElement('span')
  touchTarget.className = 'code-block-copy-target'
  touchTarget.setAttribute('aria-hidden', 'true')
  copy.prepend(touchTarget)

  copy.addEventListener('click', async () => {
    const code = block.textContent || ''
    try {
      await writeClipboard(code)
      copy.lastChild!.textContent = 'Copied'
      window.setTimeout(() => {
        if (copy.isConnected && copy.lastChild) copy.lastChild.textContent = 'Copy'
      }, 1600)
    } catch {
      copy.lastChild!.textContent = 'Copy failed'
    }
  })

  pre.before(wrapper)
  header.append(language, copy)
  wrapper.append(header, pre)
}

async function enhance() {
  await nextTick()
  root.value?.querySelectorAll<HTMLElement>('pre code').forEach((block) => {
    if (!block.dataset.highlighted) hljs.highlightElement(block)
    decorateCodeBlock(block)
  })
  root.value?.querySelectorAll<HTMLAnchorElement>('a[href]').forEach((link) => {
    if (/^https?:\/\//i.test(link.href)) {
      link.target = '_blank'
      link.rel = 'noopener noreferrer'
    }
  })
}

watch(() => props.content, enhance, { immediate: true })
</script>

<template>
  <div ref="root" class="prose max-w-[72ch]" v-html="html" />
</template>
