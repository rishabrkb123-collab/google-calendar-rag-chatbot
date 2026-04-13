import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import EventCard from './EventCard'

const mockEvent = {
  id: '1',
  title: 'Team Standup',
  start: { dateTime: '2026-04-14T09:00:00Z' },
  end: { dateTime: '2026-04-14T09:30:00Z' },
  description: 'Daily sync meeting',
  location: 'Zoom',
  allDay: false,
  colorId: null,
}

describe('EventCard', () => {
  it('renders event title', () => {
    render(<EventCard event={mockEvent} calendarColor="#4285F4" />)
    expect(screen.getByText('Team Standup')).toBeInTheDocument()
  })

  it('renders location when present', () => {
    render(<EventCard event={mockEvent} calendarColor="#4285F4" />)
    expect(screen.getByText('Zoom')).toBeInTheDocument()
  })

  it('does not render location when absent', () => {
    const noLocation = { ...mockEvent, location: '' }
    render(<EventCard event={noLocation} calendarColor="#4285F4" />)
    expect(screen.queryByText('Zoom')).not.toBeInTheDocument()
  })
})
