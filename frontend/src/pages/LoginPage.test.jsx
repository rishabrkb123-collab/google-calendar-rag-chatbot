import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { AuthContext } from '../context/AuthContext'
import LoginPage from './LoginPage'

const renderLogin = () =>
  render(
    <AuthContext.Provider value={{ isAuthenticated: false, loading: false }}>
      <MemoryRouter><LoginPage /></MemoryRouter>
    </AuthContext.Provider>
  )

describe('LoginPage', () => {
  it('renders connect button', () => {
    renderLogin()
    expect(screen.getByRole('button', { name: /connect google calendar/i })).toBeInTheDocument()
  })

  it('navigates to /auth/login on button click', () => {
    const originalLocation = window.location
    delete window.location
    window.location = { href: '' }
    renderLogin()
    fireEvent.click(screen.getByRole('button', { name: /connect google calendar/i }))
    expect(window.location.href).toBe('/auth/login')
    window.location = originalLocation
  })
})
