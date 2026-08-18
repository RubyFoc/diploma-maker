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
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
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

/**
 * Renders an "insert here" toggle beside each block (TASK-E15-3), matched positionally against
 * `blocks` the same way `LockSelectionProps.lockableBlocks` is — see that interface's doc
 * comment. Selecting a block sets it as the anchor for the next chat instruction's "insert at
 * anchor" generation; selecting the already-selected block clears it.
 */
export interface AnchorSelectionProps {
  anchorableBlocks: ManifestBlock[]
  selectedBlockId: string | null
  onSelect: (block: ManifestBlock) => void
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
  /** Renders an "insert here" anchor-selection toggle beside each rendered block when provided
   * (TASK-E15-3). Independent of `lockSelection` — both can be shown side by side. */
  anchorSelection?: AnchorSelectionProps
  /** Positionally matches `blocks`, same convention as `lockSelection.lockableBlocks` (TASK-E16-4):
   * the block id each rendered block corresponds to, or `null` for a rendered block with no
   * corresponding id (e.g. a diff segment that only exists in the "before" version). Paired with
   * `onPageBlockIdsChange` to let a caller resolve "the currently-visible page's block ids"
   * without this component needing to know anything about undo/redo itself. */
  pageBlockIds?: (string | null)[]
  /** Called with the currently-visible page's non-null block ids whenever the visible page (or
   * `pageBlockIds` itself) changes. Omit if the caller doesn't need page-level block ids. */
  onPageBlockIdsChange?: (blockIds: string[]) => void
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
  anchorSelection,
  pageBlockIds,
  onPageBlockIdsChange,
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

  // Renders `blockIndex` exactly the way the visible page does — including the lock/anchor
  // toggle button beside it, when applicable — so the off-screen measuring pass below sees the
  // same narrower content column the button's flex row produces on the real page. Without this,
  // the measuring pass rendered each block at the *full* page width (no button eating into it),
  // under-measuring its height whenever the button's presence pushed wrapped text onto an extra
  // line; a page's real (button-narrowed) content then overflowed the height computed from that
  // undercount, silently clipping the last block at the bottom of the page (user report: text
  // cut off mid-sentence at the page's bottom edge).
  const renderBlockWithControls = (blockIndex: number): ReactNode => {
    const block = blocks[blockIndex]
    const rendered = wrapBlock(block, blockIndex)
    const lockableBlock = lockSelection?.lockableBlocks[blockIndex]
    const anchorableBlock = anchorSelection?.anchorableBlocks[blockIndex]
    if (!lockableBlock && !anchorableBlock) {
      return rendered
    }
    const isLocked = lockableBlock ? lockSelection!.lockedBlockIds.has(lockableBlock.id) : false
    const isSelectedAnchor = anchorableBlock ? anchorSelection!.selectedBlockId === anchorableBlock.id : false
    return (
      <div key={blockIndex} className="document-block-with-lock">
        {lockableBlock && (
          <button
            type="button"
            className={isLocked ? 'document-block-lock-toggle document-block-lock-toggle--locked' : 'document-block-lock-toggle'}
            onClick={() => lockSelection!.onToggleLock(lockableBlock)}
            aria-pressed={isLocked}
            aria-label={isLocked ? strings.documentBlockUnlockLabel : strings.documentBlockLockLabel}
            title={isLocked ? strings.documentBlockUnlockLabel : strings.documentBlockLockLabel}
          >
            {isLocked ? '🔒' : '🔓'}
          </button>
        )}
        {anchorableBlock && (
          <button
            type="button"
            className={
              isSelectedAnchor
                ? 'document-block-anchor-toggle document-block-anchor-toggle--selected'
                : 'document-block-anchor-toggle'
            }
            onClick={() => anchorSelection!.onSelect(anchorableBlock)}
            aria-pressed={isSelectedAnchor}
            aria-label={isSelectedAnchor ? strings.documentBlockInsertHereSelectedLabel : strings.documentBlockInsertHereLabel}
            title={isSelectedAnchor ? strings.documentBlockInsertHereSelectedLabel : strings.documentBlockInsertHereLabel}
          >
            {isSelectedAnchor ? '📍' : '➕'}
          </button>
        )}
        <div className="document-block-with-lock-content">{rendered}</div>
      </div>
    )
  }

  // `blocks`/`pageStyle` are rebuilt as new array/object literals on every render by every
  // caller (`DocumentPreview`/`DiffViewer` both call `parseBlocks`/`buildTaggedBlocks` and
  // `getPageStyle` fresh inline, not memoized) — including a render triggered by THIS component's
  // own `onPageBlockIdsChange` callback below, which updates state one level up. Depending on
  // `[blocks, pageStyle]` directly (by reference) made the pagination effect re-fire on every
  // such render, unconditionally resetting `pageIndex` back to 0 — so clicking "Next" triggered
  // `onPageBlockIdsChange`, which re-rendered the parent, which produced new (but
  // content-identical) `blocks`/`pageStyle` objects, which snapped the page straight back to 1,
  // making page 2+ permanently unreachable whenever a manifest was present (real generated/
  // uploaded chapters, i.e. always in practice). Signature strings make the dependency reflect
  // actual content, not object identity, so the effect (and its `pageIndex` reset) only re-runs
  // when the content genuinely changes.
  const blocksSignature = JSON.stringify(blocks)
  const pageStyleSignature = JSON.stringify(pageStyle)

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blocksSignature, pageStyleSignature])

  const pageCount = pages.length
  const clampedIndex = pageCount === 0 ? 0 : Math.min(pageIndex, pageCount - 1)
  const currentBlockIndices = pages[clampedIndex] ?? blocks.map((_, index) => index)

  // Surfaces the currently-visible page's block ids (TASK-E16-4) without this component needing
  // to know anything about undo/redo — see `PaginatedDocumentProps.onPageBlockIdsChange`. Must
  // run unconditionally (before the `blocks.length === 0` early return below) to keep this
  // component's hook call order stable across renders.
  const visibleBlockIdsKey = pageBlockIds
    ? currentBlockIndices.map((index) => pageBlockIds[index] ?? '').join(' ')
    : ''
  useEffect(() => {
    if (!onPageBlockIdsChange) {
      return
    }
    const ids = pageBlockIds
      ? currentBlockIndices
          .map((index) => pageBlockIds[index])
          .filter((id): id is string => id != null)
      : []
    onPageBlockIdsChange(ids)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleBlockIdsKey, onPageBlockIdsChange])

  if (blocks.length === 0) {
    return emptyMessage ? <p className="document-preview-empty">{emptyMessage}</p> : null
  }

  return (
    <div className="paginated-document">
      <div className="document-page document-page--measure" style={pageStyle} aria-hidden="true">
        <div className="document-page-content" ref={measureContentRef}>
          {blocks.map((_block, index) => (
            <div
              key={index}
              ref={(el) => {
                measureRefs.current[index] = el
              }}
            >
              {renderBlockWithControls(index)}
            </div>
          ))}
        </div>
      </div>

      <div className="document-page" style={pageStyle}>
        <div className="document-page-content">
          {currentBlockIndices.map((blockIndex) => renderBlockWithControls(blockIndex))}
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
