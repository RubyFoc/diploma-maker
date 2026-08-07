import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DocumentProvider } from '../context/DocumentContext'
import { strings } from '../strings'
import { NewProjectSetup } from './NewProjectSetup'

const BASE_URL = 'http://localhost:8010'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

function renderSetup(overrides: Partial<{ onSubmit: (institutionId: string | null) => void; onCancel: () => void }> = {}) {
  const onSubmit = overrides.onSubmit ?? vi.fn()
  const onCancel = overrides.onCancel ?? vi.fn()
  render(
    <DocumentProvider>
      <NewProjectSetup onSubmit={onSubmit} onCancel={onCancel} isSubmitting={false} />
    </DocumentProvider>,
  )
  return { onSubmit, onCancel }
}

describe('NewProjectSetup', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('submits with null institution id when the user creates the project without picking one', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([])))
    const { onSubmit } = renderSetup()

    await screen.findByLabelText(strings.newProjectSetupInstitutionSelectLabel)
    fireEvent.click(screen.getByRole('button', { name: strings.newProjectSetupCreateButton }))

    expect(onSubmit).toHaveBeenCalledWith(null)
  })

  it('selecting an existing institution from the dropdown and submitting passes its id', async () => {
    const institutions = [{ institution_id: 'inst-1', institution_name: 'Test University' }]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(institutions)))
    const { onSubmit } = renderSetup()

    const select = await screen.findByLabelText(strings.newProjectSetupInstitutionSelectLabel)
    fireEvent.change(select, { target: { value: 'inst-1' } })
    fireEvent.click(screen.getByRole('button', { name: strings.newProjectSetupCreateButton }))

    expect(onSubmit).toHaveBeenCalledWith('inst-1')
  })

  it('uploading a new institution sample then submitting passes the uploaded institution id', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (String(url).includes('/formatting/institution-configs/upload')) {
        return Promise.resolve(jsonResponse({ institution_id: 'inst-2', institution_name: 'New University' }, true, 201))
      }
      return Promise.resolve(jsonResponse([]))
    })
    vi.stubGlobal('fetch', fetchMock)
    const { onSubmit } = renderSetup()

    await screen.findByLabelText(strings.newProjectSetupInstitutionSelectLabel)
    fireEvent.change(screen.getByLabelText(strings.newProjectSetupInstitutionNameLabel), {
      target: { value: 'New University' },
    })
    const file = new File(['sample'], 'sample.docx')
    const fileInput = screen.getByLabelText(strings.newProjectSetupInstitutionFileLabel)
    fireEvent.change(fileInput, { target: { files: [file] } })
    fireEvent.submit(fileInput.closest('form') as HTMLFormElement)

    await screen.findByText(strings.newProjectSetupInstitutionUploadButton)
    fireEvent.click(screen.getByRole('button', { name: strings.newProjectSetupCreateButton }))

    expect(onSubmit).toHaveBeenCalledWith('inst-2')
  })

  it('auto-detecting an institution then submitting passes the detected institution id', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (String(url).includes('/formatting/institution-configs/auto-detect')) {
        return Promise.resolve(jsonResponse({ institution_id: 'inst-3', institution_name: 'Auto University' }, true, 201))
      }
      return Promise.resolve(jsonResponse([]))
    })
    vi.stubGlobal('fetch', fetchMock)
    const { onSubmit } = renderSetup()

    await screen.findByLabelText(strings.newProjectSetupInstitutionSelectLabel)
    const nameInput = screen.getByLabelText(strings.newProjectSetupAutoDetectNameLabel)
    fireEvent.change(nameInput, { target: { value: 'Auto University' } })
    fireEvent.submit(nameInput.closest('form') as HTMLFormElement)

    await screen.findByRole('button', { name: strings.newProjectSetupAutoDetectButton })
    fireEvent.click(screen.getByRole('button', { name: strings.newProjectSetupCreateButton }))

    expect(onSubmit).toHaveBeenCalledWith('inst-3')
  })

  it('shows a calm not-found message on a 404 auto-detect and leaves the dropdown/upload options usable', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (String(url).includes('/formatting/institution-configs/auto-detect')) {
        return Promise.resolve(
          jsonResponse({ detail: "Could not automatically determine formatting requirements for 'Unknown University'." }, false, 404),
        )
      }
      return Promise.resolve(jsonResponse([]))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderSetup()

    await screen.findByLabelText(strings.newProjectSetupInstitutionSelectLabel)
    const nameInput = screen.getByLabelText(strings.newProjectSetupAutoDetectNameLabel)
    fireEvent.change(nameInput, { target: { value: 'Unknown University' } })
    fireEvent.submit(nameInput.closest('form') as HTMLFormElement)

    expect(await screen.findByText(strings.newProjectSetupAutoDetectNotFoundMessage)).toBeInTheDocument()
    expect(screen.getByLabelText(strings.newProjectSetupInstitutionSelectLabel)).toBeEnabled()
    expect(screen.getByLabelText(strings.newProjectSetupInstitutionNameLabel)).toBeEnabled()
    expect(screen.getByLabelText(strings.newProjectSetupInstitutionFileLabel)).toBeEnabled()
  })

  it('calls onCancel when Cancel is clicked', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([])))
    const { onCancel } = renderSetup()

    await screen.findByLabelText(strings.newProjectSetupInstitutionSelectLabel)
    fireEvent.click(screen.getByRole('button', { name: strings.newProjectSetupCancelButton }))

    expect(onCancel).toHaveBeenCalled()
  })

  describe('required sources (TASK-E14-4)', () => {
    beforeEach(() => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([])))
    })

    it('adding a required source with just an author queues it without a title', async () => {
      renderSetup()
      await screen.findByLabelText(strings.newProjectSetupInstitutionSelectLabel)

      fireEvent.change(screen.getByLabelText(strings.newProjectSetupRequiredSourceAuthorLabel), {
        target: { value: 'Jane Doe' },
      })
      fireEvent.click(screen.getByRole('button', { name: strings.newProjectSetupRequiredSourceAddButton }))

      expect(await screen.findByText('Jane Doe')).toBeInTheDocument()
    })

    it('adding a required source with a title queues both fields', async () => {
      renderSetup()
      await screen.findByLabelText(strings.newProjectSetupInstitutionSelectLabel)

      fireEvent.change(screen.getByLabelText(strings.newProjectSetupRequiredSourceAuthorLabel), {
        target: { value: 'Jane Doe' },
      })
      fireEvent.change(screen.getByLabelText(strings.newProjectSetupRequiredSourceTitleLabel), {
        target: { value: 'A Study of Things' },
      })
      fireEvent.click(screen.getByRole('button', { name: strings.newProjectSetupRequiredSourceAddButton }))

      expect(await screen.findByText('Jane Doe — A Study of Things')).toBeInTheDocument()
    })

    it('does not add an entry with a blank author', async () => {
      renderSetup()
      await screen.findByLabelText(strings.newProjectSetupInstitutionSelectLabel)

      fireEvent.click(screen.getByRole('button', { name: strings.newProjectSetupRequiredSourceAddButton }))

      expect(screen.queryByText(strings.newProjectSetupRequiredSourceRemoveButton)).not.toBeInTheDocument()
    })

    it('removing a queued entry drops it from the list', async () => {
      renderSetup()
      await screen.findByLabelText(strings.newProjectSetupInstitutionSelectLabel)

      fireEvent.change(screen.getByLabelText(strings.newProjectSetupRequiredSourceAuthorLabel), {
        target: { value: 'Jane Doe' },
      })
      fireEvent.click(screen.getByRole('button', { name: strings.newProjectSetupRequiredSourceAddButton }))
      await screen.findByText('Jane Doe')

      fireEvent.click(screen.getByRole('button', { name: strings.newProjectSetupRequiredSourceRemoveButton }))

      expect(screen.queryByText('Jane Doe')).not.toBeInTheDocument()
    })
  })
})
