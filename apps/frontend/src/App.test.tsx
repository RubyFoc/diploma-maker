import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from './App'
import { strings } from './strings'

describe('App', () => {
  it('renders both the chat panel and the document panel', () => {
    render(<App />)
    expect(screen.getByLabelText(strings.chatPanelTitle)).toBeInTheDocument()
    expect(screen.getByLabelText(strings.documentPanelTitle)).toBeInTheDocument()
  })

  it('starts with empty chat and document state', () => {
    render(<App />)
    expect(screen.getByText(strings.chatEmpty)).toBeInTheDocument()
    expect(screen.getByText(strings.documentEmpty)).toBeInTheDocument()
  })

  it('resets to empty state when starting a new project', async () => {
    render(<App />)
    const button = screen.getByRole('button', { name: strings.newProjectButton })
    fireEvent.click(button)
    expect(await screen.findByText(strings.chatEmpty)).toBeInTheDocument()
    expect(await screen.findByText(strings.documentEmpty)).toBeInTheDocument()
  })
})
