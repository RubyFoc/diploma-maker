import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../context/AuthContext'
import { DocumentProvider, useDocument } from '../context/DocumentContext'
import { strings } from '../strings'
import { Onboarding } from './Onboarding'

const BASE_URL = 'http://localhost:8010'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

function InstitutionIdProbe() {
  const { document: doc } = useDocument()
  return <p data-testid="institution-id">{doc.institutionId ?? 'none'}</p>
}

function PendingRequiredSourcesProbe() {
  const { document: doc } = useDocument()
  return <p data-testid="pending-required-sources">{JSON.stringify(doc.pendingRequiredSources)}</p>
}

function renderOnboarding() {
  render(
    <AuthProvider>
      <DocumentProvider>
        <Onboarding />
        <InstitutionIdProbe />
        <PendingRequiredSourcesProbe />
      </DocumentProvider>
    </AuthProvider>,
  )
}

describe('Onboarding', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('registers and advances to the institution-selection step on success', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (String(url).includes('/formatting/institution-configs')) {
        return Promise.resolve(jsonResponse([]))
      }
      return Promise.resolve(jsonResponse({ access_token: 'tok1', token_type: 'bearer' }, true, 201))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderOnboarding()

    fireEvent.change(screen.getByLabelText(strings.onboardingEmailLabel), {
      target: { value: 'user@example.com' },
    })
    fireEvent.change(screen.getByLabelText(strings.onboardingPasswordLabel), {
      target: { value: 'password123' },
    })
    fireEvent.click(screen.getByRole('button', { name: strings.onboardingRegisterButton }))

    expect(await screen.findByLabelText(strings.onboardingInstitutionStepTitle)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/auth/register`,
      expect.objectContaining({
        body: JSON.stringify({ email: 'user@example.com', password: 'password123' }),
      }),
    )
  })

  it('logs in and advances to the institution-selection step on success', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (String(url).includes('/formatting/institution-configs')) {
        return Promise.resolve(jsonResponse([]))
      }
      return Promise.resolve(jsonResponse({ access_token: 'tok2', token_type: 'bearer' }, true, 200))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderOnboarding()

    fireEvent.change(screen.getByLabelText(strings.onboardingEmailLabel), {
      target: { value: 'user@example.com' },
    })
    fireEvent.change(screen.getByLabelText(strings.onboardingPasswordLabel), {
      target: { value: 'password123' },
    })
    fireEvent.click(screen.getByRole('button', { name: strings.onboardingLoginButton }))

    expect(await screen.findByLabelText(strings.onboardingInstitutionStepTitle)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(`${BASE_URL}/auth/login`, expect.anything())
  })

  it('shows an error and does not advance when registration fails', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'already registered' }, false, 409))
    vi.stubGlobal('fetch', fetchMock)

    renderOnboarding()

    fireEvent.change(screen.getByLabelText(strings.onboardingEmailLabel), {
      target: { value: 'user@example.com' },
    })
    fireEvent.change(screen.getByLabelText(strings.onboardingPasswordLabel), {
      target: { value: 'password123' },
    })
    fireEvent.click(screen.getByRole('button', { name: strings.onboardingRegisterButton }))

    expect(await screen.findByText(strings.onboardingAuthError)).toBeInTheDocument()
    expect(screen.queryByLabelText(strings.onboardingInstitutionStepTitle)).not.toBeInTheDocument()
  })

  it('selecting an existing institution from the dropdown sets institutionId', async () => {
    const institutions = [{ institution_id: 'inst-1', institution_name: 'Test University' }]
    localStorage.setItem('diploma-maker.accessToken', 'seeded-token')
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(institutions))
    vi.stubGlobal('fetch', fetchMock)

    renderOnboarding()

    const select = await screen.findByLabelText(strings.onboardingInstitutionSelectLabel)
    fireEvent.change(select, { target: { value: 'inst-1' } })

    expect(await screen.findByTestId('institution-id')).toHaveTextContent('inst-1')
  })

  it('uploading a new institution sample sets institutionId', async () => {
    localStorage.setItem('diploma-maker.accessToken', 'seeded-token')
    const fetchMock = vi.fn((url: string) => {
      if (String(url).includes('/formatting/institution-configs/upload')) {
        return Promise.resolve(jsonResponse({ institution_id: 'inst-2', institution_name: 'New University' }, true, 201))
      }
      return Promise.resolve(jsonResponse([]))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderOnboarding()

    await screen.findByLabelText(strings.onboardingInstitutionSelectLabel)
    fireEvent.change(screen.getByLabelText(strings.onboardingInstitutionNameLabel), {
      target: { value: 'New University' },
    })
    const file = new File(['sample'], 'sample.docx')
    const fileInput = screen.getByLabelText(strings.onboardingInstitutionFileLabel)
    fireEvent.change(fileInput, { target: { files: [file] } })
    fireEvent.submit(fileInput.closest('form') as HTMLFormElement)

    expect(await screen.findByTestId('institution-id')).toHaveTextContent('inst-2')
  })

  it('auto-detecting an institution successfully sets institutionId', async () => {
    localStorage.setItem('diploma-maker.accessToken', 'seeded-token')
    const fetchMock = vi.fn((url: string) => {
      if (String(url).includes('/formatting/institution-configs/auto-detect')) {
        return Promise.resolve(jsonResponse({ institution_id: 'inst-3', institution_name: 'Auto University' }, true, 201))
      }
      return Promise.resolve(jsonResponse([]))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderOnboarding()

    await screen.findByLabelText(strings.onboardingInstitutionSelectLabel)
    const nameInput = screen.getByLabelText(strings.onboardingInstitutionAutoDetectNameLabel)
    fireEvent.change(nameInput, { target: { value: 'Auto University' } })
    fireEvent.submit(nameInput.closest('form') as HTMLFormElement)

    expect(await screen.findByTestId('institution-id')).toHaveTextContent('inst-3')
  })

  it('shows a calm not-found message on a 404 and leaves the dropdown/upload options usable', async () => {
    localStorage.setItem('diploma-maker.accessToken', 'seeded-token')
    const fetchMock = vi.fn((url: string) => {
      if (String(url).includes('/formatting/institution-configs/auto-detect')) {
        return Promise.resolve(
          jsonResponse({ detail: "Could not automatically determine formatting requirements for 'Unknown University'." }, false, 404),
        )
      }
      return Promise.resolve(jsonResponse([]))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderOnboarding()

    await screen.findByLabelText(strings.onboardingInstitutionSelectLabel)
    const nameInput = screen.getByLabelText(strings.onboardingInstitutionAutoDetectNameLabel)
    fireEvent.change(nameInput, { target: { value: 'Unknown University' } })
    fireEvent.submit(nameInput.closest('form') as HTMLFormElement)

    expect(await screen.findByText(strings.onboardingInstitutionAutoDetectNotFoundMessage)).toBeInTheDocument()
    expect(screen.getByTestId('institution-id')).toHaveTextContent('none')

    expect(screen.getByLabelText(strings.onboardingInstitutionSelectLabel)).toBeEnabled()
    expect(screen.getByLabelText(strings.onboardingInstitutionNameLabel)).toBeEnabled()
    expect(screen.getByLabelText(strings.onboardingInstitutionFileLabel)).toBeEnabled()
  })

  describe('required sources (TASK-E14-4)', () => {
    beforeEach(() => {
      localStorage.setItem('diploma-maker.accessToken', 'seeded-token')
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([])))
    })

    it('adding a required source with just an author queues it without a title', async () => {
      renderOnboarding()
      await screen.findByLabelText(strings.onboardingInstitutionSelectLabel)

      fireEvent.change(screen.getByLabelText(strings.onboardingRequiredSourceAuthorLabel), {
        target: { value: 'Jane Doe' },
      })
      fireEvent.click(screen.getByRole('button', { name: strings.onboardingRequiredSourceAddButton }))

      expect(await screen.findByText('Jane Doe')).toBeInTheDocument()
      expect(screen.getByTestId('pending-required-sources')).toHaveTextContent(
        JSON.stringify([{ author: 'Jane Doe' }]),
      )
    })

    it('adding a required source with a title queues both fields', async () => {
      renderOnboarding()
      await screen.findByLabelText(strings.onboardingInstitutionSelectLabel)

      fireEvent.change(screen.getByLabelText(strings.onboardingRequiredSourceAuthorLabel), {
        target: { value: 'Jane Doe' },
      })
      fireEvent.change(screen.getByLabelText(strings.onboardingRequiredSourceTitleLabel), {
        target: { value: 'A Study of Things' },
      })
      fireEvent.click(screen.getByRole('button', { name: strings.onboardingRequiredSourceAddButton }))

      expect(await screen.findByText('Jane Doe — A Study of Things')).toBeInTheDocument()
    })

    it('does not add an entry with a blank author', async () => {
      renderOnboarding()
      await screen.findByLabelText(strings.onboardingInstitutionSelectLabel)

      fireEvent.click(screen.getByRole('button', { name: strings.onboardingRequiredSourceAddButton }))

      expect(screen.getByTestId('pending-required-sources')).toHaveTextContent('[]')
    })

    it('clears the input fields after adding an entry', async () => {
      renderOnboarding()
      await screen.findByLabelText(strings.onboardingInstitutionSelectLabel)

      const authorInput = screen.getByLabelText(strings.onboardingRequiredSourceAuthorLabel)
      fireEvent.change(authorInput, { target: { value: 'Jane Doe' } })
      fireEvent.click(screen.getByRole('button', { name: strings.onboardingRequiredSourceAddButton }))

      expect(authorInput).toHaveValue('')
    })

    it('removing a queued entry drops it from the list', async () => {
      renderOnboarding()
      await screen.findByLabelText(strings.onboardingInstitutionSelectLabel)

      fireEvent.change(screen.getByLabelText(strings.onboardingRequiredSourceAuthorLabel), {
        target: { value: 'Jane Doe' },
      })
      fireEvent.click(screen.getByRole('button', { name: strings.onboardingRequiredSourceAddButton }))
      await screen.findByText('Jane Doe')

      fireEvent.click(screen.getByRole('button', { name: strings.onboardingRequiredSourceRemoveButton }))

      expect(screen.queryByText('Jane Doe')).not.toBeInTheDocument()
      expect(screen.getByTestId('pending-required-sources')).toHaveTextContent('[]')
    })
  })
})
