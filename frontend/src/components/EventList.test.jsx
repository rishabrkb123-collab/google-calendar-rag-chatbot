import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import EventList from './EventList'

const mockEvents = [
  {
    id: '1',
    title: 'Standup',
    start: { dateTime: '2026-04-14T09:00:00Z' },
    end: { dateTime: '2026-04-14T09:30:00Z' },
    description: '',
    location: '',
    allDay: false,
    colorId: null,
  },
  {
    id: '2',
    title: 'Lunch',
    start: { dateTime: '2026-04-14T12:00:00Z' },
    end: { dateTime: '2026-04-14T13:00:00Z' },
    description: '',
    location: 'Cafeteria',
    allDay: false,
    colorId: null,
  },
]

describe('EventList', () => {
  it('renders all events', () => {
    render(<EventList events={mockEvents} calendars={[]} loading={false} />)
    expect(screen.getByText('Standup')).toBeInTheDocument()
    expect(screen.getByText('Lunch')).toBeInTheDocument()
  })

  it('shows loading state', () => {
    render(<EventList events={[]} calendars={[]} loading={true} />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it('shows empty state when no events', () => {
    render(<EventList events={[]} calendars={[]} loading={false} />)
    expect(screen.getByText(/no events found/i)).toBeInTheDocument()
  })
})
