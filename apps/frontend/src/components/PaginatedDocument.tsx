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
import type { ManifestBlock } from '../types/project'
import './PaginatedDocument.css'

export interface LockSelectionProps {
  /** The chapter's block manifest (ADR-0011), in `order`. Matched positionally against the
   * rendered `blocks` array — see `PaginatedDocument`'s doc comment for why this is only exact
   * for list-free prose, and approximate otherwise. */
  lockableBlocks: ManifestBlock[]
  lockedBlockIds: Set<string>
  onToggleLock: (block: ManifestBlock) => void
}

export interface PaginatedDocumentProps {
  blocks: Block[]
  pageStyle: CSSProperties
  headingStyle?: (level: 1 | 2 | 3) => CSSProperties
  renderBlock?: (block: Block, key: number) => ReactNode
  emptyMessage?: string
  /** Renders a lock/unlock toggle beside each rendered block when provided (TASK-E13-5). Omit
   * entirely for read-only rendering (e.g. `DiffViewer`, where locking mid-diff-review doesn't
   * apply — see that component's doc comment). */
  lockSelection?: LockSelectionProps
}

function headingLevel(block: Block): 1 | 2 | 3 | null {
  if (block.kind === 'h1') return 1
  if (block.kind === 'h2') return 2
  if (block.kind === 'h3') return 3
  return null
}

/**
 * Renders `blocks` as paginated "paper sheet" pages (TASK-E10-4), optionally with a lock/unlock
 * toggle beside each block (`lockSelection`, TASK-E13-5, ADR-0011).
 *
 * Lock/unlock note: `lockSelection.lockableBlocks` is the backend's block manifest — one entry
 * per non-blank *line* of the chapter's raw content (`locks.models.split_into_blocks`) — matched
 * here purely by array position against `blocks`, this component's semantically-parsed render
 * blocks (headings/paragraphs/lists; see `utils/renderMarkdownPreview`). The two line up exactly
 * for list-free prose (a heading or paragraph is always exactly one manifest line), which is the
 * common case for thesis body text. They diverge for `ul`/`ol`: several manifest lines (one per
 * list item) collapse into a single rendered list block, so locking that one visual block only
 * locks the manifest block sharing its position, not every item in the list. Acceptable for this
 * first UI-selection pass (no inline markers, per TASK-E13-5's own scope) — sub-block precision
 * exists in the model (`ManifestBlock`/`Lock.char_range`) for a later refinement.
 */
export function PaginatedDocument({
  blocks,
  pageStyle,
  headingStyle,
  renderBlock,
  emptyMessage,
  lockSelection,
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
          {currentBlockIndices.map((blockIndex) => {
            const rendered = wrapBlock(blocks[blockIndex], blockIndex)
            if (!lockSelection) {
              return rendered
            }
            const lockableBlock = lockSelection.lockableBlocks[blockIndex]
            if (!lockableBlock) {
              return rendered
            }
            const isLocked = lockSelection.lockedBlockIds.has(lockableBlock.id)
            return (
              <div key={blockIndex} className="document-block-with-lock">
                <button
                  type="button"
                  className={isLocked ? 'document-block-lock-toggle document-block-lock-toggle--locked' : 'document-block-lock-toggle'}
                  onClick={() => lockSelection.onToggleLock(lockableBlock)}
                  aria-pressed={isLocked}
                  aria-label={isLocked ? strings.documentBlockUnlockLabel : strings.documentBlockLockLabel}
                  title={isLocked ? strings.documentBlockUnlockLabel : strings.documentBlockLockLabel}
                >
                  {isLocked ? '🔒' : '🔓'}
                </button>
                <div className="document-block-with-lock-content">{rendered}</div>
              </div>
            )
          })}
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
