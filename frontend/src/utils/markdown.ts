import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'

// =====================================================================
// Markdown 渲染 + 代码高亮
// =====================================================================

let mdInstance: MarkdownIt | null = null

function createMd(): MarkdownIt {
  return new MarkdownIt({
    html: false,
    linkify: true,
    typographer: true,
    breaks: true,
    highlight(code: string, lang: string): string {
      const language = hljs.getLanguage(lang)
      if (language) {
        try {
          const highlighted = hljs.highlight(code, { language: lang, ignoreIllegals: true }).value
          return `<pre><code class="hljs language-${lang}">${highlighted}</code></pre>`
        } catch {
          // fallthrough to escape
        }
      }
      return `<pre><code class="hljs">${MarkdownIt().utils.escapeHtml(code)}</code></pre>`
    },
  })
}

function getMd(): MarkdownIt {
  if (!mdInstance) mdInstance = createMd()
  return mdInstance
}

/** 将 Markdown 文本渲染为安全的 HTML */
export function renderMarkdown(text: string): string {
  if (!text) return ''
  return getMd().render(text)
}
