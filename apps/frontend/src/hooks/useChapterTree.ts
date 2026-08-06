import { useEffect, useState } from 'react'
import { createSubchapter, listSubchapters } from '../services/projectService'
import type { ChapterDetail } from '../types/project'

export interface ChapterTreeNode {
  chapter: ChapterDetail
  subchapters: ChapterDetail[]
}

export interface UseChapterTreeResult {
  nodes: ChapterTreeNode[]
  isLoading: boolean
  /** Creates a subchapter under `chapterId` and folds it into that node's `subchapters`. */
  addSubchapter: (chapterId: string, title: string) => Promise<void>
}

/**
 * Builds a two-level chapter/subchapter tree for the sidebar (TASK-E12-4, ADR-0014's two-level
 * nesting cap) from a project's top-level `chapters` (as returned by `ProjectDetail`, which
 * already excludes subchapters per `projects.router._build_project_detail`). Fetches each
 * chapter's subchapters with one `listSubchapters` call per chapter — acceptable at this scale
 * (a thesis has a handful of chapters, not hundreds) rather than requiring a combined backend
 * endpoint.
 */
export function useChapterTree(
  projectId: string | null,
  chapters: ChapterDetail[],
): UseChapterTreeResult {
  const [nodes, setNodes] = useState<ChapterTreeNode[]>([])
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    if (projectId === null || chapters.length === 0) {
      setNodes([])
      setIsLoading(false)
      return
    }

    let cancelled = false
    setIsLoading(true)

    Promise.all(
      chapters.map((chapter) =>
        listSubchapters(projectId, chapter.id)
          .then((subchapters) => ({ chapter, subchapters }))
          .catch(() => ({ chapter, subchapters: [] as ChapterDetail[] })),
      ),
    ).then((result) => {
      if (!cancelled) {
        setNodes(result)
        setIsLoading(false)
      }
    })

    return () => {
      cancelled = true
    }
    // `chapters` is derived fresh from ProjectDetail on every fetch, so comparing by the ids/
    // count that actually change avoids refetching subchapters on every unrelated re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, chapters.map((chapter) => chapter.id).join(',')])

  const addSubchapter = async (chapterId: string, title: string) => {
    if (projectId === null) {
      return
    }
    const created = await createSubchapter(projectId, chapterId, title)
    setNodes((previous) =>
      previous.map((node) =>
        node.chapter.id === chapterId
          ? { ...node, subchapters: [...node.subchapters, created] }
          : node,
      ),
    )
  }

  return { nodes, isLoading, addSubchapter }
}
