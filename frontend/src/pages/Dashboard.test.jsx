import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { AuthContext } from '../context/AuthContext'
import Dashboard from './Dashboard'
import api from '../api/client'

vi.mock('../api/client')

const authValue = { isAuthenticated: true, user: { email: 'test@example.com' }, loading: false, logout: vi.fn() }

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
      if (url === '/api/calendars') return Promise.resolve({ data: [{ id: 'primary', name: 'My Cal', color: '#4285F4' }] })
      if (url.startsWith('/api/events')) return Promise.resolve({ data: { events: [
        { id: '1', title: 'Test Event', start: { dateTime: '2026-04-14T09:00:00Z' }, end: { dateTime: '2026-04-14T10:00:00Z' }, description: '', location: '', allDay: false }
      ], nextPageToken: null } })
      return Promise.resolve({ data: {} })
    })
    render(
      <AuthContext.Provider value={authValue}>
        <MemoryRouter><Dashboard /></MemoryRouter>
      </AuthContext.Provider>
    )
    await waitFor(() => expect(screen.getByText('Test Event')).toBeInTheDocument())
  })
})
