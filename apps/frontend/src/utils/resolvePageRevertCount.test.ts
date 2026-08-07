import { describe, expect, it } from 'vitest'
import { resolvePageRedoCount, resolvePageUndoCount } from './resolvePageRevertCount'
import type { OperationSummary } from '../types/history'

function op(id: string, blockId: string): OperationSummary {
  return { id, block_id: blockId, created_at: 'now' }
}

describe('resolvePageUndoCount', () => {
  it('resolves the contiguous case: all of a page ops trail at the tail', () => {
    const operations = [op('o1', 'other-a'), op('o2', 'page-a'), op('o3', 'page-b')]
    const result = resolvePageUndoCount(operations, 3, new Set(['page-a', 'page-b']))

    expect(result).toEqual({ count: 2, spansOtherEdits: false, otherEditsCount: 0, widerCount: 2 })
  })

  it('detects the non-contiguous case and reports the wider count/other-edits warning', () => {
    // page-a is applied, then some unrelated block, then page-b at the tail. Reverting "this
    // page" from the tail only reaches page-b before hitting the unrelated op.
    const operations = [op('o1', 'page-a'), op('o2', 'other'), op('o3', 'page-b')]
    const result = resolvePageUndoCount(operations, 3, new Set(['page-a', 'page-b']))

    expect(result.spansOtherEdits).toBe(true)
    expect(result.count).toBe(1)
    expect(result.widerCount).toBe(3)
    expect(result.otherEditsCount).toBe(1)
  })

  it('is a no-op when the most-recently-applied operation does not touch this page', () => {
    const operations = [op('o1', 'page-a'), op('o2', 'other')]
    const result = resolvePageUndoCount(operations, 2, new Set(['page-a']))

    expect(result).toEqual({ count: 0, spansOtherEdits: false, otherEditsCount: 0, widerCount: 0 })
  })

  it('only considers already-applied operations, ignoring the still-undone redo tail', () => {
    const operations = [op('o1', 'page-a'), op('o2', 'page-a')]
    // Only the first operation is applied; the second is a redo-tail entry that shouldn't count.
    const result = resolvePageUndoCount(operations, 1, new Set(['page-a']))

    expect(result).toEqual({ count: 1, spansOtherEdits: false, otherEditsCount: 0, widerCount: 1 })
  })
})

describe('resolvePageRedoCount', () => {
  it('resolves the contiguous case: all of a page ops lead the undone tail', () => {
    const operations = [op('o1', 'page-a'), op('o2', 'page-b'), op('o3', 'other')]
    const result = resolvePageRedoCount(operations, 0, new Set(['page-a', 'page-b']))

    expect(result).toEqual({ count: 2, spansOtherEdits: false, otherEditsCount: 0, widerCount: 2 })
  })

  it('detects the non-contiguous case for redo and reports the wider count', () => {
    const operations = [op('o1', 'page-a'), op('o2', 'other'), op('o3', 'page-b')]
    const result = resolvePageRedoCount(operations, 0, new Set(['page-a', 'page-b']))

    expect(result.spansOtherEdits).toBe(true)
    expect(result.count).toBe(1)
    expect(result.widerCount).toBe(3)
    expect(result.otherEditsCount).toBe(1)
  })

  it('is a no-op when the next-to-redo operation does not touch this page', () => {
    const operations = [op('o1', 'other'), op('o2', 'page-a')]
    const result = resolvePageRedoCount(operations, 0, new Set(['page-a']))

    expect(result).toEqual({ count: 0, spansOtherEdits: false, otherEditsCount: 0, widerCount: 0 })
  })
})
