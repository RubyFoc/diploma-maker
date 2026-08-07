import { useEffect, useState } from 'react'
import { RequestError, listOperations, redoChapter, undoChapter } from '../services/historyService'
import type { OperationsListResponse } from '../types/history'
import type { ChapterVersion } from '../types/project'

export interface UseChapterHistoryResult {
  /** `null` while loading or when `chapterId` is `null` (no pending draft to act on, per
   * `DocumentPanel`'s call site — see that component for why history is only fetched while a
   * draft is pending). */
  history: OperationsListResponse | null
  isLoading: boolean
  /** Set after a failed `undo`/`redo` call, until the next attempt starts. `'conflict'` for a
   * 409 (someone else undid/redid concurrently, or an anchor block genuinely vanished);
   * `'generic'` for anything else (network failure, etc). */
  error: 'conflict' | 'generic' | null
  undo: (count: number) => Promise<void>
  redo: (count: number) => Promise<void>
}

/**
 * Tracks `chapterId`'s undo/redo op-log (ADR-0012, TASK-E16-2/3/4/5) and exposes `undo`/`redo`
 * actions that mutate the chapter's pending draft in place, reporting the result back via
 * `onVersionUpdated` so the caller can update whatever local state represents that draft (e.g.
 * `DocumentContext`'s `Chapter.pendingDraft`) — this hook holds no draft-content state of its
 * own, only the op-log position (`applied_count`/`total_operations`), matching
 * `useChapterLocks`'s split between "this hook's own concern" and "state the caller already
 * owns".
 *
 * `draftKey` should identify the current pending draft (e.g. its `id` or `version_number`), not
 * just `chapterId`: a second anchor-mode generation on the same chapter produces a new draft
 * without changing `chapterId`, but rewrites the op-log tail on the backend, so the op-log must
 * be refetched whenever the draft itself changes, not only when the chapter does.
 */
export function useChapterHistory(
  chapterId: string | null,
  onVersionUpdated: (version: ChapterVersion) => void,
  draftKey?: string | number | null,
): UseChapterHistoryResult {
  const [history, setHistory] = useState<OperationsListResponse | null>(null)
  const [isLoading, setIsLoading] = useState(chapterId !== null)
  const [error, setError] = useState<'conflict' | 'generic' | null>(null)

  useEffect(() => {
    setError(null)

    if (chapterId === null) {
      setHistory(null)
      setIsLoading(false)
      return
    }

    let cancelled = false
    setIsLoading(true)

    listOperations(chapterId)
      .then((result) => {
        if (!cancelled) {
          setHistory(result)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setHistory(null)
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
    // `draftKey` (e.g. the pending draft's id/version) is included so that a second anchor-mode
    // generation on the SAME chapter — which rewrites the op-log tail server-side (see
    // `record_anchor_insertion_operations`) — refetches instead of leaving `history` stale.
  }, [chapterId, draftKey])

  const runUndo = async (count: number) => {
    if (chapterId === null || count < 1) {
      return
    }
    setError(null)
    try {
      const result = await undoChapter(chapterId, count)
      onVersionUpdated(result.version)
      setHistory({ operations: history?.operations ?? [], applied_count: result.applied_count, total_operations: result.total_operations })
    } catch (caught) {
      setError(caught instanceof RequestError && caught.status === 409 ? 'conflict' : 'generic')
    }
  }

  const runRedo = async (count: number) => {
    if (chapterId === null || count < 1) {
      return
    }
    setError(null)
    try {
      const result = await redoChapter(chapterId, count)
      onVersionUpdated(result.version)
      setHistory({ operations: history?.operations ?? [], applied_count: result.applied_count, total_operations: result.total_operations })
    } catch (caught) {
      setError(caught instanceof RequestError && caught.status === 409 ? 'conflict' : 'generic')
    }
  }

  return { history, isLoading, error, undo: runUndo, redo: runRedo }
}
