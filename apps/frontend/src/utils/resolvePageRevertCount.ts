/**
 * Client-side page-range revert resolution (TASK-E16-4, ADR-0012).
 *
 * "Page" is never a stored backend concept and the op-log is strictly linear (ADR-0012):
 * undo/redo only ever operate on the tail. Reverting/reapplying "this page" is therefore not a
 * true range-targeted undo — it's arithmetic that figures out how many TRAILING operations to
 * undo (or how many leading undone operations to redo) via a plain `count`, which only correctly
 * captures a page's edits when they're contiguous at the tail (the common case: generating
 * content on the page you're currently looking at).
 *
 * Both directions share the same shape of answer:
 * - `count`: how many operations are trailing-contiguous matches for the page. `0` means the
 *   most-recently-applied (undo) / next-to-redo (redo) operation doesn't even touch this page —
 *   there's nothing to do, and the caller must not send `count: 0` (the backend requires `>= 1`).
 * - `spansOtherEdits`: `true` when the page has additional matching operations *beyond* the
 *   contiguous run — i.e. some other block's edit sits between the tail and where the rest of
 *   this page's history lives. In that case, `count` alone under-reverts the page, and reaching
 *   `widerCount` would also revert `otherEditsCount` unrelated operations — neither should happen
 *   silently, so the caller must warn before acting on `widerCount`.
 */
import type { OperationSummary } from '../types/history'

export interface PageRevertResolution {
  /** Contiguous trailing match count — safe to send as-is, but see `spansOtherEdits`. */
  count: number
  /** Whether this page's operations are NOT all contiguous at the tail. */
  spansOtherEdits: boolean
  /** How many other blocks' operations sit between the tail and the rest of this page's history;
   * only meaningful when `spansOtherEdits` is true. */
  otherEditsCount: number
  /** The count needed to also capture the non-contiguous, further-back operations for this page
   * (equal to `count` when `spansOtherEdits` is false). */
  widerCount: number
}

const NO_OP: PageRevertResolution = { count: 0, spansOtherEdits: false, otherEditsCount: 0, widerCount: 0 }

function countMatches(range: OperationSummary[], pageBlockIds: ReadonlySet<string>): number {
  return range.filter((operation) => pageBlockIds.has(operation.block_id)).length
}

/** Shared resolution over a pre-sliced, already-ordered `range` (oldest-first) walked from one
 * end (`fromStart` walks index 0 upward — the redo direction; otherwise walks from the end
 * downward — the undo direction). */
function resolve(range: OperationSummary[], pageBlockIds: ReadonlySet<string>, fromStart: boolean): PageRevertResolution {
  let contiguousCount = 0
  if (fromStart) {
    while (contiguousCount < range.length && pageBlockIds.has(range[contiguousCount].block_id)) {
      contiguousCount += 1
    }
  } else {
    let index = range.length - 1
    while (index >= 0 && pageBlockIds.has(range[index].block_id)) {
      contiguousCount += 1
      index -= 1
    }
  }

  if (contiguousCount === 0) {
    return NO_OP
  }

  const totalInRange = countMatches(range, pageBlockIds)
  if (contiguousCount === totalInRange) {
    return { count: contiguousCount, spansOtherEdits: false, otherEditsCount: 0, widerCount: contiguousCount }
  }

  let widerCount: number
  if (fromStart) {
    let lastMatchIndex = -1
    for (let i = range.length - 1; i >= 0; i -= 1) {
      if (pageBlockIds.has(range[i].block_id)) {
        lastMatchIndex = i
        break
      }
    }
    widerCount = lastMatchIndex + 1
  } else {
    let firstMatchIndex = range.length
    for (let i = 0; i < range.length; i += 1) {
      if (pageBlockIds.has(range[i].block_id)) {
        firstMatchIndex = i
        break
      }
    }
    widerCount = range.length - firstMatchIndex
  }

  return {
    count: contiguousCount,
    spansOtherEdits: true,
    otherEditsCount: widerCount - totalInRange,
    widerCount,
  }
}

/** Resolves "undo this page" into a `count` (TASK-E16-4): walks the currently-applied operations
 * backward from `appliedCount - 1`, counting trailing entries whose `block_id` is in
 * `pageBlockIds`. */
export function resolvePageUndoCount(
  operations: OperationSummary[],
  appliedCount: number,
  pageBlockIds: ReadonlySet<string>,
): PageRevertResolution {
  return resolve(operations.slice(0, appliedCount), pageBlockIds, false)
}

/** Resolves "redo this page" into a `count` (TASK-E16-4): the mirror of
 * `resolvePageUndoCount`, walking the still-undone tail forward from `appliedCount`. */
export function resolvePageRedoCount(
  operations: OperationSummary[],
  appliedCount: number,
  pageBlockIds: ReadonlySet<string>,
): PageRevertResolution {
  return resolve(operations.slice(appliedCount), pageBlockIds, true)
}
