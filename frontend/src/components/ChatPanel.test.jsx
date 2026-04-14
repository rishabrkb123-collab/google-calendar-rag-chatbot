import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import ChatPanel from './ChatPanel'
import api from '../api/client'

vi.mock('../api/client')

describe('ChatPanel', () => {
  it('submits a message and renders the assistant response', async () => {
    api.post = vi.fn().mockResolvedValue({
      data: {
        answer: 'You have 3 meetings tomorrow.',
        actions: [],
        events: [],
      },
    })

    render(<ChatPanel />)

    fireEvent.change(screen.getByLabelText('Calendar chat input'), { target: { value: 'What do I have tomorrow?' } })
    fireEvent.click(screen.getByText('Send'))

    await waitFor(() => expect(screen.getByText('You have 3 meetings tomorrow.')).toBeInTheDocument())
    expect(api.post).toHaveBeenCalledWith('/chat', expect.objectContaining({ message: 'What do I have tomorrow?' }))
  })

  it('does not send the canned starter message in chat history', async () => {
    api.post = vi.fn().mockResolvedValue({
      data: {
        answer: 'You have nothing scheduled.',
        actions: [],
        events: [],
      },
    })

    render(<ChatPanel />)

    fireEvent.change(screen.getByLabelText('Calendar chat input'), { target: { value: 'What do I have today?' } })
    fireEvent.click(screen.getByText('Send'))

    await waitFor(() => expect(api.post).toHaveBeenCalled())
    expect(api.post).toHaveBeenCalledWith('/chat', {
      message: 'What do I have today?',
      history: [],
    })
  })
})
