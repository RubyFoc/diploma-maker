import { useEffect, useState } from 'react'
import { createLock, deleteLock, listLocks } from '../services/lockService'
import type { ManifestBlock } from '../types/project'

export interface UseChapterLocksResult {
  /** `block.id`s currently locked, for O(1) "is this block locked?" lookups while rendering. */
  lockedBlockIds: Set<string>
  isLoading: boolean
  /** Locks `block` if unlocked, unlocks it if already locked. Errors (e.g. a stale hash, 409) are
   * swallowed — the lock state simply doesn't change, same fail-quiet posture as
   * `useInstitutionConfig`'s network-failure handling, since this is a best-effort UI toggle, not
   * a flow with its own error banner. */
  toggleLock: (block: ManifestBlock) => Promise<void>
}

/**
 * Tracks which blocks of `chapterId`'s current accepted content are locked (TASK-E13-4/E13-5,
 * ADR-0011), and lets the UI toggle a block's lock state.
 *
 * Fetches the existing locks once on mount/`chapterId` change; `toggleLock` is optimistic-free
 * (awaits the API call, then updates local state from the result) since lock/unlock are rare,
 * deliberate user actions, not something that needs to feel instantaneous under network latency.
 */
export function useChapterLocks(chapterId: string | null): UseChapterLocksResult {
  const [lockIdByBlockId, setLockIdByBlockId] = useState<Map<string, string>>(new Map())
  const [isLoading, setIsLoading] = useState(chapterId !== null)

  useEffect(() => {
    if (chapterId === null) {
      setLockIdByBlockId(new Map())
      setIsLoading(false)
      return
    }

    let cancelled = false
    setIsLoading(true)

    listLocks(chapterId)
      .then((locks) => {
        if (!cancelled) {
          setLockIdByBlockId(new Map(locks.map((lock) => [lock.block_id, lock.id])))
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLockIdByBlockId(new Map())
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
  }, [chapterId])

  const toggleLock = async (block: ManifestBlock) => {
    if (chapterId === null) {
      return
    }
    const existingLockId = lockIdByBlockId.get(block.id)
    try {
      if (existingLockId !== undefined) {
        await deleteLock(chapterId, existingLockId)
        setLockIdByBlockId((previous) => {
          const next = new Map(previous)
          next.delete(block.id)
          return next
        })
      } else {
        const lock = await createLock(chapterId, block.id, block.content_hash)
        setLockIdByBlockId((previous) => new Map(previous).set(block.id, lock.id))
      }
    } catch {
      // Fail-quiet, see UseChapterLocksResult.toggleLock's doc comment.
    }
  }

  return { lockedBlockIds: new Set(lockIdByBlockId.keys()), isLoading, toggleLock }
}
