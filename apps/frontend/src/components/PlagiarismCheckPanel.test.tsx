import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PlagiarismCheckPanel } from './PlagiarismCheckPanel'
import { strings } from '../strings'

const BASE_URL = 'http://localhost:8010'

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

async function typeAndCheck(text: string) {
  const textarea = screen.getByLabelText(strings.plagiarismCheckTextareaPlaceholder)
  fireEvent.change(textarea, { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: strings.plagiarismCheckButton }))
}

describe('PlagiarismCheckPanel', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('checks the typed text and displays both scores', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ plagiarism_score: 0.12, ai_fingerprint_score: 0.34, flagged: false, reasons: [] }),
    )
    vi.stubGlobal('fetch', fetchMock)

    render(<PlagiarismCheckPanel />)
    await typeAndCheck('My own academic text')

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/plagiarism/check`,
      expect.objectContaining({ body: JSON.stringify({ text: 'My own academic text' }) }),
    )
    expect(await screen.findByText(/12%/)).toBeInTheDocument()
    expect(await screen.findByText(/34%/)).toBeInTheDocument()
  })

  it('shows a flagged banner and reasons distinctly when flagged is true', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        plagiarism_score: 0.9,
        ai_fingerprint_score: 0.8,
        flagged: true,
        reasons: ['high similarity to known source'],
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    render(<PlagiarismCheckPanel />)
    await typeAndCheck('Some suspicious text')

    expect(await screen.findByText(strings.plagiarismCheckFlaggedMessage)).toBeInTheDocument()
    expect(screen.getByText('high similarity to known source')).toBeInTheDocument()
    expect(screen.getByText(strings.plagiarismCheckFlaggedMessage)).toHaveClass(
      'plagiarism-check-banner--flagged',
    )
  })

  it('shows a not-flagged banner without reasons when flagged is false', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ plagiarism_score: 0.05, ai_fingerprint_score: 0.02, flagged: false, reasons: [] }),
    )
    vi.stubGlobal('fetch', fetchMock)

    render(<PlagiarismCheckPanel />)
    await typeAndCheck('Clean original text')

    expect(await screen.findByText(strings.plagiarismCheckNotFlaggedMessage)).toBeInTheDocument()
    expect(screen.getByText(strings.plagiarismCheckNotFlaggedMessage)).toHaveClass(
      'plagiarism-check-banner--clear',
    )
    expect(screen.queryByText(strings.plagiarismCheckReasonsTitle)).not.toBeInTheDocument()
  })

  it('shows an error message and does not crash when the check fails', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'text is required' }, false, 422))
    vi.stubGlobal('fetch', fetchMock)

    render(<PlagiarismCheckPanel />)
    await typeAndCheck('Text that will fail')

    expect(await screen.findByText(strings.plagiarismCheckErrorMessage)).toBeInTheDocument()
  })

  it('disables the check button while a check is in-flight', async () => {
    const fetchMock = vi.fn().mockReturnValue(new Promise<Response>(() => {}))
    vi.stubGlobal('fetch', fetchMock)

    render(<PlagiarismCheckPanel />)
    const textarea = screen.getByLabelText(strings.plagiarismCheckTextareaPlaceholder)
    fireEvent.change(textarea, { target: { value: 'Some text' } })
    fireEvent.click(screen.getByRole('button', { name: strings.plagiarismCheckButton }))

    expect(await screen.findByRole('button', { name: strings.plagiarismCheckButtonPending })).toBeDisabled()
  })
})
