/**
 * Markdown-subset → JSX renderer for the live document preview (TASK-E08-4).
 *
 * Parses the exact Markdown subset the platform's LLM content generation is expected to
 * produce and that `apps/backend/src/diploma_backend/export/docx.py`'s `markdown_to_docx`
 * renders into `.docx`: headings (`#`/`##`/`###`), blank-line-separated paragraphs, inline
 * `**bold**`/`*italic*`, unordered lists (`-`/`*`), ordered lists (`1.`), and the
 * `[[figure: <description>]]` media placeholder. This keeps the live preview visually
 * consistent with the final exported document.
 *
 * Written by hand (no `react-markdown`/`marked`/etc.) — same "small line-based parsing
 * utility instead of a new dependency" approach as `utils/diff.ts`'s from-scratch diff
 * algorithm, since the supported subset is small and fixed.
 *
 * Anything outside this subset (tables, blockquotes, code fences, nested lists, links, `####`+
 * headings, ...) is never dropped: it falls through and renders as plain paragraph text
 * containing the literal source line, mirroring the backend engine's fail-safe fallback.
 */
import type { ReactNode } from 'react'

type Block =
  | { kind: 'h1' | 'h2' | 'h3'; text: string }
  | { kind: 'p'; text: string }
  | { kind: 'ul' | 'ol'; items: string[] }
  | { kind: 'figure'; text: string }

const HEADING_RE = /^(#{1,3})\s+(.*)$/
const UNORDERED_LIST_RE = /^[-*]\s+(.*)$/
const ORDERED_LIST_RE = /^\d+\.\s+(.*)$/
const FIGURE_PLACEHOLDER_RE = /^\[\[figure:\s*(.+?)\s*\]\]$/i
const INLINE_RE = /\*\*(.+?)\*\*|\*(.+?)\*/g

function parseBlocks(markdownText: string): Block[] {
  const blocks: Block[] = []
  let paragraphBuffer: string[] = []
  let listBuffer: { type: 'ul' | 'ol'; items: string[] } | null = null

  const flushParagraph = () => {
    if (paragraphBuffer.length > 0) {
      blocks.push({ kind: 'p', text: paragraphBuffer.join(' ') })
      paragraphBuffer = []
    }
  }
  const flushList = () => {
    if (listBuffer) {
      blocks.push({ kind: listBuffer.type, items: listBuffer.items })
      listBuffer = null
    }
  }

  for (const rawLine of markdownText.split('\n')) {
    const line = rawLine.trim()

    if (line === '') {
      flushParagraph()
      flushList()
      continue
    }

    const headingMatch = HEADING_RE.exec(line)
    if (headingMatch) {
      flushParagraph()
      flushList()
      const level = headingMatch[1].length
      blocks.push({ kind: (`h${level}` as 'h1' | 'h2' | 'h3'), text: headingMatch[2] })
      continue
    }

    const unorderedMatch = UNORDERED_LIST_RE.exec(line)
    if (unorderedMatch) {
      flushParagraph()
      if (!listBuffer || listBuffer.type !== 'ul') {
        flushList()
        listBuffer = { type: 'ul', items: [] }
      }
      listBuffer.items.push(unorderedMatch[1])
      continue
    }

    const orderedMatch = ORDERED_LIST_RE.exec(line)
    if (orderedMatch) {
      flushParagraph()
      if (!listBuffer || listBuffer.type !== 'ol') {
        flushList()
        listBuffer = { type: 'ol', items: [] }
      }
      listBuffer.items.push(orderedMatch[1])
      continue
    }

    const figureMatch = FIGURE_PLACEHOLDER_RE.exec(line)
    if (figureMatch) {
      flushParagraph()
      flushList()
      blocks.push({ kind: 'figure', text: figureMatch[1] })
      continue
    }

    // Plain text, and unsupported constructs (tables/blockquotes/code fences/...) accumulate
    // as literal paragraph text — never silently dropped, per the backend engine's contract.
    flushList()
    paragraphBuffer.push(line)
  }

  flushParagraph()
  flushList()
  return blocks
}

/** Renders `**bold**`/`*italic*` inline markup within `text` as `<strong>`/`<em>` nodes. */
function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = []
  let position = 0
  let key = 0

  for (const match of text.matchAll(INLINE_RE)) {
    const start = match.index ?? 0
    if (start > position) {
      nodes.push(text.slice(position, start))
    }

    const [, boldText, italicText] = match
    if (boldText !== undefined) {
      nodes.push(<strong key={key}>{boldText}</strong>)
    } else {
      nodes.push(<em key={key}>{italicText}</em>)
    }
    key += 1
    position = start + match[0].length
  }

  if (position < text.length) {
    nodes.push(text.slice(position))
  }

  return nodes
}

/**
 * Parses `markdownText` (the same Markdown subset `export/docx.py` supports) and returns React
 * elements for it — headings, paragraphs, lists, and figure placeholders, with inline
 * bold/italic applied, plus a plain-text fallback for anything unsupported.
 */
export function renderMarkdownPreview(markdownText: string): ReactNode[] {
  return parseBlocks(markdownText).map((block, index) => {
    switch (block.kind) {
      case 'h1':
        return <h1 key={index}>{renderInline(block.text)}</h1>
      case 'h2':
        return <h2 key={index}>{renderInline(block.text)}</h2>
      case 'h3':
        return <h3 key={index}>{renderInline(block.text)}</h3>
      case 'ul':
        return (
          <ul key={index}>
            {block.items.map((item, itemIndex) => (
              <li key={itemIndex}>{renderInline(item)}</li>
            ))}
          </ul>
        )
      case 'ol':
        return (
          <ol key={index}>
            {block.items.map((item, itemIndex) => (
              <li key={itemIndex}>{renderInline(item)}</li>
            ))}
          </ol>
        )
      case 'figure':
        return (
          <p key={index} className="preview-figure-placeholder" data-testid="preview-figure-placeholder">
            [FIGURE PLACEHOLDER: {block.text}]
          </p>
        )
      case 'p':
        return <p key={index}>{renderInline(block.text)}</p>
    }
  })
}
