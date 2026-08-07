import { describe, expect, it } from 'vitest'
import type { ProjectDetail } from '../types/project'
import { toDocumentState } from './mapProject'

function buildProject(overrides: Partial<ProjectDetail> = {}): ProjectDetail {
  return {
    id: 'p1',
    title: 'Untitled',
    created_at: 'now',
    chapters: [],
    ...overrides,
  }
}

describe('toDocumentState', () => {
  it('reads institutionId off the project itself (TASK-INT-17/18: per-project, not carried over)', () => {
    const state = toDocumentState(buildProject({ institution_id: 'inst-1' }))
    expect(state.institutionId).toBe('inst-1')
  })

  it('defaults institutionId to null when the project has none', () => {
    const state = toDocumentState(buildProject({ institution_id: null }))
    expect(state.institutionId).toBeNull()
  })

  it('defaults institutionId to null when the field is absent entirely', () => {
    const state = toDocumentState(buildProject())
    expect(state.institutionId).toBeNull()
  })

  it('always starts pendingRequiredSources empty', () => {
    const state = toDocumentState(buildProject())
    expect(state.pendingRequiredSources).toEqual([])
  })
})
