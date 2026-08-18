import { useEffect, useState } from 'react'
import './ProjectLanding.css'
import { useChat } from '../context/ChatContext'
import { emptyDocumentState, useDocument } from '../context/DocumentContext'
import { useNewProject } from '../hooks/useNewProject'
import { strings } from '../strings'
import { deleteProject, getProject, listProjects } from '../services/projectService'
import type { ProjectSummary } from '../types/project'
import { toDocumentState } from '../utils/mapProject'
import { NewProjectSetup } from './NewProjectSetup'

interface ProjectLandingProps {
  /** Called once a project becomes active (created or opened), so the caller can enter the workspace view. */
  onProjectActivated: () => void
}

/**
 * Full-page project list shown before entering the chat+preview workspace (TASK-E11-4 follow-up:
 * was previously a header dropdown, `ProjectSwitcher`). Loads the caller's projects on mount,
 * lets them create a new one, open an existing one, or delete one (behind a two-step confirm, per
 * the diff accept/reject contract's spirit of never silently discarding user work on a single
 * click).
 */
export function ProjectLanding({ onProjectActivated }: ProjectLandingProps) {
  const { document: doc, setDocument } = useDocument()
  const { clearChat, loadChatForProject, deleteChatForProject } = useChat()
  const startNewProject = useNewProject()
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null)
  const [loadError, setLoadError] = useState(false)
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null)
  const [deleteErrorId, setDeleteErrorId] = useState<string | null>(null)
  const [isCreating, setIsCreating] = useState(false)
  const [createError, setCreateError] = useState(false)
  const [isSettingUpNewProject, setIsSettingUpNewProject] = useState(false)

  const loadProjects = async () => {
    setLoadError(false)
    try {
      const result = await listProjects()
      setProjects(result)
    } catch {
      setLoadError(true)
    }
  }

  useEffect(() => {
    void loadProjects()
  }, [])

  const handleCreate = async (institutionId: string | null) => {
    if (isCreating) {
      return
    }
    setIsCreating(true)
    setCreateError(false)
    try {
      await startNewProject(institutionId)
      setIsSettingUpNewProject(false)
      onProjectActivated()
    } catch {
      setCreateError(true)
    } finally {
      setIsCreating(false)
    }
  }

  const handleSwitch = async (projectId: string) => {
    // Re-entering the already-active project (e.g. via "My Projects" then "Open") shouldn't
    // refetch or reset the in-progress chat — only switching to a *different* project does.
    if (projectId === doc.projectId) {
      onProjectActivated()
      return
    }
    const project = await getProject(projectId)
    setDocument(() => toDocumentState(project))
    loadChatForProject(project.id)
    onProjectActivated()
  }

  const handleDelete = async (projectId: string) => {
    setDeleteErrorId(null)
    try {
      await deleteProject(projectId)
      setProjects((previous) => previous?.filter((project) => project.id !== projectId) ?? previous)
      setConfirmingDeleteId(null)
      deleteChatForProject(projectId)
      if (doc.projectId === projectId) {
        setDocument((previous) => ({ ...emptyDocumentState, institutionId: previous.institutionId }))
        clearChat()
      }
    } catch {
      setDeleteErrorId(projectId)
    }
  }

  const handleCancelNewProjectSetup = () => {
    setIsSettingUpNewProject(false)
    // Discard anything the user queued in the cancelled attempt — otherwise a required source
    // entered here would silently resurface (and get submitted) the next time "New Project" is
    // opened, even though the user explicitly backed out of this attempt.
    setDocument((previous) => ({ ...previous, pendingRequiredSources: [] }))
  }

  if (isSettingUpNewProject) {
    return (
      <NewProjectSetup
        onSubmit={(institutionId) => void handleCreate(institutionId)}
        onCancel={handleCancelNewProjectSetup}
        isSubmitting={isCreating}
        submitError={createError ? strings.newProjectSetupCreateError : null}
      />
    )
  }

  return (
    <section className="project-landing" aria-label={strings.projectLandingTitle}>
      <div className="project-landing-header">
        <h2>{strings.projectLandingTitle}</h2>
        <button type="button" onClick={() => setIsSettingUpNewProject(true)} disabled={isCreating}>
          {strings.newProjectButton}
        </button>
      </div>
      {loadError && <p className="project-landing-error">{strings.projectLandingLoadErrorMessage}</p>}
      {projects !== null && projects.length === 0 && !loadError && (
        <p className="project-landing-empty">{strings.projectLandingEmpty}</p>
      )}
      {projects !== null && projects.length > 0 && (
        <ul className="project-landing-list">
          {projects.map((project) => {
            const isActive = doc.projectId === project.id
            return (
              <li key={project.id} className="project-landing-item">
                <span className="project-landing-item-title">
                  {project.title}
                  {isActive ? ` (${strings.projectLandingActiveLabel})` : ''}
                </span>
                <span className="project-landing-item-date">
                  {new Date(project.created_at).toLocaleDateString()}
                </span>
                <button type="button" onClick={() => void handleSwitch(project.id)}>
                  {strings.projectLandingOpenButton}
                </button>
                {confirmingDeleteId === project.id ? (
                  <>
                    <button type="button" onClick={() => void handleDelete(project.id)}>
                      {strings.projectLandingDeleteConfirmButton}
                    </button>
                    <button type="button" onClick={() => setConfirmingDeleteId(null)}>
                      {strings.projectLandingDeleteCancelButton}
                    </button>
                  </>
                ) : (
                  <button type="button" onClick={() => setConfirmingDeleteId(project.id)}>
                    {strings.projectLandingDeleteButton}
                  </button>
                )}
                {deleteErrorId === project.id && (
                  <span className="project-landing-delete-error">
                    {strings.projectLandingDeleteErrorMessage}
                  </span>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
