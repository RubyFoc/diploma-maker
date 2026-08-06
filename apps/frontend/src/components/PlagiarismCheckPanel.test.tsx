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

  it('checks the typed text and displays all three scores', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        plagiarism_score: 0.12,
        ai_fingerprint_score: 0.34,
        originality_score: 0.88,
        flagged: false,
        reasons: [],
        sentence_flags: [],
      }),
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
    expect(await screen.findByText(/88%/)).toBeInTheDocument()
  })

  it('highlights plagiarized and AI-like sentences distinctly', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        plagiarism_score: 0.6,
        ai_fingerprint_score: 0.5,
        originality_score: 0.4,
        flagged: true,
        reasons: ['high similarity to known source'],
        sentence_flags: [
          { text: 'This is a clean sentence.', plagiarism_score: 0.05, is_plagiarized: false, is_ai_like: false },
          { text: 'This is a copied sentence.', plagiarism_score: 0.9, is_plagiarized: true, is_ai_like: false },
          { text: 'This is an AI-like sentence.', plagiarism_score: 0.3, is_plagiarized: false, is_ai_like: true },
        ],
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    render(<PlagiarismCheckPanel />)
    await typeAndCheck('Some text with repeated sentence starters. This is a clean sentence.')

    expect(await screen.findByText(strings.plagiarismCheckSentenceFlagsTitle)).toBeInTheDocument()
    expect(screen.getByText('This is a copied sentence.')).toHaveClass('plagiarism-check-sentence--plagiarized')
    expect(screen.getByText('This is an AI-like sentence.')).toHaveClass('plagiarism-check-sentence--ai-like')
    expect(screen.getByText('This is a clean sentence.')).not.toHaveClass(
      'plagiarism-check-sentence--plagiarized',
    )
  })

  it('shows a flagged banner and reasons distinctly when flagged is true', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        plagiarism_score: 0.9,
        ai_fingerprint_score: 0.8,
        originality_score: 0.1,
        flagged: true,
        reasons: ['high similarity to known source'],
        sentence_flags: [],
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
      jsonResponse({
        plagiarism_score: 0.05,
        ai_fingerprint_score: 0.02,
        originality_score: 0.95,
        flagged: false,
        reasons: [],
        sentence_flags: [],
      }),
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

  it('switches to file mode and checks an uploaded file against /plagiarism/check-file', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        plagiarism_score: 0.1,
        ai_fingerprint_score: 0.2,
        originality_score: 0.9,
        flagged: false,
        reasons: [],
        sentence_flags: [],
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    render(<PlagiarismCheckPanel />)
    fireEvent.click(screen.getByRole('tab', { name: strings.plagiarismCheckModeFileLabel }))

    const fileInput = screen.getByLabelText(strings.plagiarismUploadFileLabel)
    const file = new File(['content'], 'thesis.docx', {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    })
    fireEvent.change(fileInput, { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: strings.plagiarismUploadButton }))

    expect(await screen.findByText(/90%/)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(`${BASE_URL}/plagiarism/check-file`, expect.objectContaining({ method: 'POST' }))
  })

  it('clears the previous result when switching modes', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        plagiarism_score: 0.12,
        ai_fingerprint_score: 0.34,
        originality_score: 0.88,
        flagged: false,
        reasons: [],
        sentence_flags: [],
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    render(<PlagiarismCheckPanel />)
    await typeAndCheck('My own academic text')
    expect(await screen.findByText(/88%/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: strings.plagiarismCheckModeFileLabel }))
    expect(screen.queryByText(/88%/)).not.toBeInTheDocument()
  })
})
