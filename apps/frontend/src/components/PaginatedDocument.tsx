/**
 * Slices a flat `Block[]` into pages sized like a real exported document page, instead of
 * one continuous scroll (TASK-E10-4).
 *
 * There is no reliable way to compute a block's rendered height from `pageStyle` alone —
 * line-wrapping depends on the browser's actual font metrics — so this measures real DOM
 * heights: every block is rendered once into an off-screen container using the exact page
 * width/padding/font, each block's `offsetHeight` is read via a ref, and pages are filled
 * greedily up to the page content area's own measured `clientHeight`.
 */
import { useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { renderBlock as defaultRenderBlock } from '../utils/renderMarkdownPreview'
import type { Block } from '../utils/renderMarkdownPreview'
import { strings } from '../strings'
import './PaginatedDocument.css'

export interface PaginatedDocumentProps {
  blocks: Block[]
  pageStyle: CSSProperties
  headingStyle?: (level: 1 | 2 | 3) => CSSProperties
  renderBlock?: (block: Block, key: number) => ReactNode
  emptyMessage?: string
}

function headingLevel(block: Block): 1 | 2 | 3 | null {
  if (block.kind === 'h1') return 1
  if (block.kind === 'h2') return 2
  if (block.kind === 'h3') return 3
  return null
}

export function PaginatedDocument({
  blocks,
  pageStyle,
  headingStyle,
  renderBlock,
  emptyMessage,
}: PaginatedDocumentProps) {
  const renderFn = renderBlock ?? defaultRenderBlock
  const measureRefs = useRef<(HTMLDivElement | null)[]>([])
  const measureContentRef = useRef<HTMLDivElement | null>(null)
  const [pages, setPages] = useState<number[][]>([])
  const [pageIndex, setPageIndex] = useState(0)

  // Renders `block` via `renderFn`, then wraps headings in a heading-level-specific style
  // (institution-configured font size/weight) without needing `renderFn` itself to know
  // about heading styling — `fontSize`/`fontWeight` are inherited CSS properties, so a
  // styled wrapper affects the heading element inside it the same as styling it directly.
  const wrapBlock = (block: Block, key: number): ReactNode => {
    const node = renderFn(block, key)
    const level = headingLevel(block)
    if (level === null || !headingStyle) {
      return node
    }
    const style = headingStyle(level)
    return Object.keys(style).length > 0 ? (
      <div key={key} style={style}>
        {node}
      </div>
    ) : (
      node
    )
  }

  useLayoutEffect(() => {
    setPageIndex(0)

    if (blocks.length === 0) {
      setPages([])
      return
    }

    const contentEl = measureContentRef.current
    const availableHeight = contentEl?.clientHeight ?? 0
    const heights = measureRefs.current.map((el) => el?.offsetHeight ?? 0)

    const computedPages: number[][] = []
    let currentPage: number[] = []
    let currentHeight = 0

    heights.forEach((height, index) => {
      // Always place at least one block per page, even if that block alone overflows
      // the page, to avoid an infinite/empty-page loop for unusually tall content.
      if (currentPage.length > 0 && currentHeight + height > availableHeight) {
        computedPages.push(currentPage)
        currentPage = []
        currentHeight = 0
      }
      currentPage.push(index)
      currentHeight += height
    })
    if (currentPage.length > 0) {
      computedPages.push(currentPage)
    }

    setPages(computedPages)
  }, [blocks, pageStyle])

  if (blocks.length === 0) {
    return emptyMessage ? <p className="document-preview-empty">{emptyMessage}</p> : null
  }

  const pageCount = pages.length
  const clampedIndex = pageCount === 0 ? 0 : Math.min(pageIndex, pageCount - 1)
  const currentBlockIndices = pages[clampedIndex] ?? blocks.map((_, index) => index)

  return (
    <div className="paginated-document">
      <div className="document-page document-page--measure" style={pageStyle} aria-hidden="true">
        <div className="document-page-content" ref={measureContentRef}>
          {blocks.map((block, index) => (
            <div
              key={index}
              ref={(el) => {
                measureRefs.current[index] = el
              }}
            >
              {wrapBlock(block, index)}
            </div>
          ))}
        </div>
      </div>

      <div className="document-page" style={pageStyle}>
        <div className="document-page-content">
          {currentBlockIndices.map((blockIndex) => wrapBlock(blocks[blockIndex], blockIndex))}
        </div>
      </div>

      {pageCount > 1 && (
        <div className="document-page-nav">
          <button
            type="button"
            onClick={() => setPageIndex((previous) => Math.max(0, previous - 1))}
            disabled={clampedIndex === 0}
          >
            {strings.documentPagePrevButton}
          </button>
          <span>{strings.documentPageLabel(clampedIndex + 1, pageCount)}</span>
          <button
            type="button"
            onClick={() => setPageIndex((previous) => Math.min(pageCount - 1, previous + 1))}
            disabled={clampedIndex === pageCount - 1}
          >
            {strings.documentPageNextButton}
          </button>
        </div>
      )}
    </div>
  )
}
