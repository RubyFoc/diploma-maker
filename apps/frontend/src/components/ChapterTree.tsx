import { useState } from 'react'
import './ChapterTree.css'
import { useChapterTree } from '../hooks/useChapterTree'
import { strings } from '../strings'
import type { ChapterDetail } from '../types/project'

interface ChapterTreeProps {
  projectId: string | null
  /** Top-level chapters only (matches `ProjectDetail.chapters`, per `projects.router._build_project_detail`). */
  chapters: ChapterDetail[]
  selectedChapterId: string | null
  onSelectChapter: (chapterId: string) => void
}

/**
 * Sidebar navigation over a project's chapter/subchapter tree (TASK-E12-4, ADR-0014). Two levels
 * deep, matching the backend's nesting cap: each top-level chapter can be expanded to reveal its
 * subchapters (fetched via `useChapterTree`), and a small inline form lets the user add a new
 * subchapter under a chapter without leaving the sidebar.
 */
export function ChapterTree({ projectId, chapters, selectedChapterId, onSelectChapter }: ChapterTreeProps) {
  const { nodes, isLoading, addSubchapter } = useChapterTree(projectId, chapters)
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())
  const [addingUnderId, setAddingUnderId] = useState<string | null>(null)
  const [newSubchapterTitle, setNewSubchapterTitle] = useState('')
  const [addError, setAddError] = useState<string | null>(null)

  const toggleExpanded = (chapterId: string) => {
    setExpandedIds((previous) => {
      const next = new Set(previous)
      if (next.has(chapterId)) {
        next.delete(chapterId)
      } else {
        next.add(chapterId)
      }
      return next
    })
  }

  const startAdding = (chapterId: string) => {
    setAddingUnderId(chapterId)
    setNewSubchapterTitle('')
    setAddError(null)
  }

  const cancelAdding = () => {
    setAddingUnderId(null)
    setNewSubchapterTitle('')
    setAddError(null)
  }

  const confirmAdding = async (chapterId: string) => {
    const title = newSubchapterTitle.trim()
    if (title === '') {
      return
    }
    try {
      await addSubchapter(chapterId, title)
      setExpandedIds((previous) => new Set(previous).add(chapterId))
      cancelAdding()
    } catch {
      setAddError(chapterId)
    }
  }

  if (!isLoading && nodes.length === 0) {
    return (
      <nav className="chapter-tree" aria-label={strings.chapterTreeTitle}>
        <h3>{strings.chapterTreeTitle}</h3>
        <p className="chapter-tree-empty">{strings.chapterTreeEmpty}</p>
      </nav>
    )
  }

  return (
    <nav className="chapter-tree" aria-label={strings.chapterTreeTitle}>
      <h3>{strings.chapterTreeTitle}</h3>
      <ul className="chapter-tree-list">
        {nodes.map(({ chapter, subchapters }) => {
          const isExpanded = expandedIds.has(chapter.id)
          const isSelected = selectedChapterId === chapter.id
          return (
            <li key={chapter.id} className="chapter-tree-node">
              <div className="chapter-tree-item">
                {subchapters.length > 0 && (
                  <button
                    type="button"
                    className="chapter-tree-toggle"
                    onClick={() => toggleExpanded(chapter.id)}
                    aria-label={isExpanded ? strings.chapterTreeCollapseLabel : strings.chapterTreeExpandLabel}
                  >
                    {isExpanded ? '▾' : '▸'}
                  </button>
                )}
                <button
                  type="button"
                  className={
                    isSelected ? 'chapter-tree-title chapter-tree-item--selected' : 'chapter-tree-title'
                  }
                  onClick={() => onSelectChapter(chapter.id)}
                >
                  {chapter.title}
                </button>
                <button
                  type="button"
                  className="chapter-tree-add-button"
                  onClick={() => startAdding(chapter.id)}
                >
                  {strings.chapterTreeAddSubchapterButton}
                </button>
              </div>

              {addingUnderId === chapter.id && (
                <form
                  className="chapter-tree-add-form"
                  onSubmit={(event) => {
                    event.preventDefault()
                    void confirmAdding(chapter.id)
                  }}
                >
                  <input
                    type="text"
                    value={newSubchapterTitle}
                    onChange={(event) => setNewSubchapterTitle(event.target.value)}
                    placeholder={strings.chapterTreeAddSubchapterInputLabel}
                    aria-label={strings.chapterTreeAddSubchapterInputLabel}
                    autoFocus
                  />
                  <button type="submit">{strings.chapterTreeAddSubchapterConfirmButton}</button>
                  <button type="button" onClick={cancelAdding}>
                    {strings.chapterTreeAddSubchapterCancelButton}
                  </button>
                </form>
              )}
              {addError === chapter.id && (
                <p className="chapter-tree-add-error">{strings.chapterTreeAddSubchapterErrorMessage}</p>
              )}

              {isExpanded && subchapters.length > 0 && (
                <ul className="chapter-tree-sublist">
                  {subchapters.map((subchapter) => (
                    <li key={subchapter.id} className="chapter-tree-subnode">
                      <button
                        type="button"
                        className={
                          selectedChapterId === subchapter.id
                            ? 'chapter-tree-title chapter-tree-item--selected'
                            : 'chapter-tree-title'
                        }
                        onClick={() => onSelectChapter(subchapter.id)}
                      >
                        {subchapter.title}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
