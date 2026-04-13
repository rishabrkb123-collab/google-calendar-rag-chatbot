import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { AuthProvider, useAuth } from './AuthContext'
import api from '../api/client'

vi.mock('../api/client')

function TestConsumer() {
  const { isAuthenticated, user, loading } = useAuth()
  if (loading) return <div>Loading</div>
  return (
    <div>
      <span data-testid="auth">{isAuthenticated ? 'yes' : 'no'}</span>
      <span data-testid="email">{user?.email ?? 'none'}</span>
    </div>
  )
}

describe('AuthContext', () => {
  it('shows unauthenticated when API returns false', async () => {
    api.get = vi.fn().mockResolvedValue({ data: { authenticated: false, email: null } })
    render(<AuthProvider><TestConsumer /></AuthProvider>)
    await waitFor(() => expect(screen.getByTestId('auth').textContent).toBe('no'))
    expect(screen.getByTestId('email').textContent).toBe('none')
  })

  it('shows authenticated with email when API returns true', async () => {
    api.get = vi.fn().mockResolvedValue({ data: { authenticated: true, email: 'user@example.com' } })
    render(<AuthProvider><TestConsumer /></AuthProvider>)
    await waitFor(() => expect(screen.getByTestId('auth').textContent).toBe('yes'))
    expect(screen.getByTestId('email').textContent).toBe('user@example.com')
  })
})
