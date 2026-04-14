import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { AuthContext } from '../context/AuthContext'
import Dashboard from './Dashboard'
import api from '../api/client'

vi.mock('../api/client')

const authValue = { isAuthenticated: true, user: { email: 'test@example.com' }, loading: false, logout: vi.fn() }

vi.mock('date-fns', async () => {
  const actual = await vi.importActual('date-fns')
  return {
    ...actual,
    formatISO: () => '2026-04-14T00:00:00Z',
  }
})

describe('Dashboard', () => {
  it('shows loading spinner initially', () => {
    api.get = vi.fn().mockReturnValue(new Promise(() => {}))
    render(
      <AuthContext.Provider value={authValue}>
        <MemoryRouter><Dashboard /></MemoryRouter>
      </AuthContext.Provider>
    )
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it('renders events after loading', async () => {
    api.get = vi.fn().mockImplementation((url) => {
      if (url === '/api/calendars') return Promise.resolve({ data: [{ id: 'primary', name: 'My Cal', color: '#4285F4', isHoliday: false, isBirthday: false }] })
      if (url.startsWith('/api/events/all')) return Promise.resolve({ data: { events: [
        { id: '1', title: 'Test Event', start: { dateTime: '2026-04-14T09:00:00Z' }, end: { dateTime: '2026-04-14T10:00:00Z' }, description: '', location: '', allDay: false }
      ] } })
      return Promise.resolve({ data: {} })
    })
    render(
      <AuthContext.Provider value={authValue}>
        <MemoryRouter><Dashboard /></MemoryRouter>
      </AuthContext.Provider>
    )
    await waitFor(() => expect(screen.getByText('Test Event')).toBeInTheDocument())
  })

  it('loads all pages across selected calendars', async () => {
    api.get = vi.fn().mockImplementation((url) => {
      if (url === '/api/calendars') {
        return Promise.resolve({
          data: [
            { id: 'primary', name: 'My Cal', color: '#4285F4', isHoliday: false, isBirthday: false },
            { id: 'work', name: 'Work', color: '#0F9D58', isHoliday: false, isBirthday: false },
          ],
        })
      }

      if (url.startsWith('/api/events/all')) {
        return Promise.resolve({
          data: {
            events: [
              { id: 'p1', calendarId: 'primary', title: 'Primary Page 1', start: { dateTime: '2026-04-14T09:00:00Z' }, end: { dateTime: '2026-04-14T10:00:00Z' }, description: '', location: '', allDay: false },
              { id: 'p2', calendarId: 'primary', title: 'Primary Page 2', start: { dateTime: '2026-04-14T11:00:00Z' }, end: { dateTime: '2026-04-14T12:00:00Z' }, description: '', location: '', allDay: false },
              { id: 'w1', calendarId: 'work', title: 'Work Calendar Event', start: { dateTime: '2026-04-14T10:00:00Z' }, end: { dateTime: '2026-04-14T10:30:00Z' }, description: '', location: '', allDay: false },
            ],
          },
        })
      }

      return Promise.resolve({ data: { events: [] } })
    })

    render(
      <AuthContext.Provider value={authValue}>
        <MemoryRouter><Dashboard /></MemoryRouter>
      </AuthContext.Provider>
    )

    await waitFor(() => expect(screen.getByText('Primary Page 1')).toBeInTheDocument())
    expect(screen.getByText('Work Calendar Event')).toBeInTheDocument()
    expect(screen.getByText('Primary Page 2')).toBeInTheDocument()
  })

  it('renders a setup error when calendar API access is disabled', async () => {
    api.get = vi.fn().mockImplementation((url) => {
      if (url === '/api/calendars') {
        return Promise.reject({
          response: {
            data: {
              detail: {
                message: 'Google Calendar API is disabled for the current Google Cloud project.',
                resolution: 'Enable the Google Calendar API in Google Cloud Console for this OAuth project, wait a few minutes, then sign in again.',
                setupUrl: 'https://console.developers.google.com',
              },
            },
          },
        })
      }
      return Promise.resolve({ data: { events: [] } })
    })

    render(
      <AuthContext.Provider value={authValue}>
        <MemoryRouter><Dashboard /></MemoryRouter>
      </AuthContext.Provider>
    )

    await waitFor(() => expect(screen.getByText(/calendar data could not be loaded/i)).toBeInTheDocument())
    expect(screen.getByText(/google calendar api is disabled/i)).toBeInTheDocument()
  })

  it('does not apply an upcoming date range by default', async () => {
    api.get = vi.fn().mockImplementation((url) => {
      if (url === '/api/calendars') {
        return Promise.resolve({ data: [{ id: 'primary', name: 'My Cal', color: '#4285F4', isHoliday: false, isBirthday: false }] })
      }

      if (url.startsWith('/api/events/all')) {
        expect(url).not.toContain('from_date=')
        expect(url).not.toContain('to_date=')
        return Promise.resolve({ data: { events: [] } })
      }

      return Promise.resolve({ data: {} })
    })

    render(
      <AuthContext.Provider value={authValue}>
        <MemoryRouter><Dashboard /></MemoryRouter>
      </AuthContext.Provider>
    )

    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/calendars'))
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/api/events/all?')))
  })

  it('does not auto-select holiday calendars by default', async () => {
    api.get = vi.fn().mockImplementation((url) => {
      if (url === '/api/calendars') {
        return Promise.resolve({
          data: [
            { id: 'primary', name: 'My Cal', color: '#4285F4', isHoliday: false, isBirthday: false },
            { id: 'en.indian#holiday@group.v.calendar.google.com', name: 'Indian Holidays', color: '#0F9D58', isHoliday: true, isBirthday: false },
          ],
        })
      }

      if (url.startsWith('/api/events/all')) {
        expect(url).toContain('calendarIds=primary')
        expect(url).not.toContain('holiday%40group')
        return Promise.resolve({ data: { events: [] } })
      }

      return Promise.resolve({ data: {} })
    })

    render(
      <AuthContext.Provider value={authValue}>
        <MemoryRouter><Dashboard /></MemoryRouter>
      </AuthContext.Provider>
    )

    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining('calendarIds=primary')))
  })

  it('applies upcoming as an open-ended future filter', async () => {
    api.get = vi.fn().mockImplementation((url) => {
      if (url === '/api/calendars') {
        return Promise.resolve({ data: [{ id: 'primary', name: 'My Cal', color: '#4285F4', isHoliday: false, isBirthday: false }] })
      }

      if (url.startsWith('/api/events/all')) {
        if (url.includes('from_date=')) {
          expect(url).not.toContain('to_date=')
        }
        return Promise.resolve({ data: { events: [] } })
      }

      return Promise.resolve({ data: {} })
    })

    render(
      <AuthContext.Provider value={authValue}>
        <MemoryRouter><Dashboard /></MemoryRouter>
      </AuthContext.Provider>
    )

    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/calendars'))
    fireEvent.click(screen.getByText('Upcoming'))
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining('from_date=')))
  })

  it('refreshes events when refresh is clicked', async () => {
    api.get = vi.fn().mockImplementation((url) => {
      if (url === '/api/calendars') {
        return Promise.resolve({ data: [{ id: 'primary', name: 'My Cal', color: '#4285F4', isHoliday: false, isBirthday: false }] })
      }

      if (url.startsWith('/api/events/all')) {
        return Promise.resolve({ data: { events: [] } })
      }

      return Promise.resolve({ data: {} })
    })

    render(
      <AuthContext.Provider value={authValue}>
        <MemoryRouter><Dashboard /></MemoryRouter>
      </AuthContext.Provider>
    )

    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/calendars'))
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/api/events/all?')))

    const initialEventCalls = api.get.mock.calls.filter(([url]) => url.startsWith('/api/events/all')).length
    fireEvent.click(screen.getByText('Refresh'))

    await waitFor(() => {
      const refreshedEventCalls = api.get.mock.calls.filter(([url]) => url.startsWith('/api/events/all')).length
      expect(refreshedEventCalls).toBeGreaterThan(initialEventCalls)
    })
  })
})
