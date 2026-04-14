import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import EventDetailsModal from './EventDetailsModal'
import api from '../api/client'

vi.mock('../api/client')

const mockEvent = {
  id: '1',
  calendarId: 'primary',
  title: 'Team Standup',
  start: { dateTime: '2026-04-14T09:00:00Z' },
  end: { dateTime: '2026-04-14T09:30:00Z' },
  description: 'Daily sync meeting',
  location: 'Zoom',
  allDay: false,
  attendees: [],
  recurrence: [],
}

describe('EventDetailsModal', () => {
  beforeEach(() => {
    api.get = vi.fn().mockResolvedValue({ data: mockEvent })
    api.patch = vi.fn().mockResolvedValue({ data: mockEvent })
    api.delete = vi.fn().mockResolvedValue({ data: { ok: true } })
  })

  it('loads event details for viewing', async () => {
    render(<EventDetailsModal event={mockEvent} mode="view" onClose={() => {}} onEventSaved={() => {}} onEventDeleted={() => {}} />)
    await waitFor(() => expect(screen.getByDisplayValue('Team Standup')).toBeInTheDocument())
  })

  it('submits event updates', async () => {
    render(<EventDetailsModal event={mockEvent} mode="edit" onClose={() => {}} onEventSaved={() => {}} onEventDeleted={() => {}} />)
    await waitFor(() => expect(screen.getByDisplayValue('Team Standup')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Updated Standup' } })
    fireEvent.click(screen.getByText('Save Changes'))
    await waitFor(() => expect(api.patch).toHaveBeenCalled())
  })

  it('asks for confirmation before deleting', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<EventDetailsModal event={mockEvent} mode="edit" onClose={() => {}} onEventSaved={() => {}} onEventDeleted={() => {}} />)
    await waitFor(() => expect(screen.getByText('Delete')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Delete'))

    expect(confirmSpy).toHaveBeenCalledWith('Delete "Team Standup"?')
    await waitFor(() => expect(api.delete).toHaveBeenCalled())

    confirmSpy.mockRestore()
  })
})
