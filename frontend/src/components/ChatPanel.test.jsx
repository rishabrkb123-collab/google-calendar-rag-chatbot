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

  it('sends selected event and calendar ids after a clarification card tap', async () => {
    api.post = vi.fn()
      .mockResolvedValueOnce({
        data: {
          answer: 'Tap the matching event.',
          mode: 'clarification',
          actions: [],
          events: [
            {
              id: 'evt-1',
              calendarId: 'work',
              title: 'Routine dental checkup',
              start: { dateTime: '2026-04-30T17:00:00+05:30' },
              end: { dateTime: '2026-04-30T18:00:00+05:30' },
            },
          ],
          pending_plan: {
            action: 'update_event',
            target_hint: 'Routine dental checkup',
            updates: {},
          },
        },
      })
      .mockResolvedValueOnce({
        data: {
          answer: 'Updated the event.',
          mode: 'action',
          actions: [{ type: 'update_event' }],
          events: [],
        },
      })

    render(<ChatPanel />)

    fireEvent.change(screen.getByLabelText('Calendar chat input'), { target: { value: 'Move my dental checkup' } })
    fireEvent.click(screen.getByText('Send'))

    await waitFor(() => expect(screen.getByText('Routine dental checkup')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Routine dental checkup'))

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2))
    expect(api.post).toHaveBeenNthCalledWith(
      2,
      '/chat',
      expect.objectContaining({
        history: expect.arrayContaining([
          expect.objectContaining({ role: 'assistant', mode: 'clarification' }),
        ]),
        selected_event_id: 'evt-1',
        selected_calendar_id: 'work',
      }),
    )
  })
})
