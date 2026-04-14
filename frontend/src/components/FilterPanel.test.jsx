import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import FilterPanel from './FilterPanel'

const mockCalendars = [
  { id: 'primary', name: 'My Calendar', color: '#4285F4' },
  { id: 'work', name: 'Work', color: '#0F9D58' },
]

const defaultFilters = { calendarIds: ['primary', 'work'], fromDate: '', toDate: '', quickFilter: '' }

describe('FilterPanel', () => {
  it('renders all calendars as checkboxes', () => {
    render(
      <FilterPanel
        calendars={mockCalendars}
        filters={defaultFilters}
        onChange={() => {}}
      />
    )
    expect(screen.getByLabelText('My Calendar')).toBeInTheDocument()
    expect(screen.getByLabelText('Work')).toBeInTheDocument()
  })

  it('calls onChange when quick filter is clicked', () => {
    const onChange = vi.fn()
    render(
      <FilterPanel
        calendars={mockCalendars}
        filters={defaultFilters}
        onChange={onChange}
      />
    )
    fireEvent.click(screen.getByText('Today'))
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ quickFilter: 'today' }))
  })

  it('clears quick filter when a custom date is selected', () => {
    const onChange = vi.fn()
    render(
      <FilterPanel
        calendars={mockCalendars}
        filters={{ ...defaultFilters, quickFilter: 'all' }}
        onChange={onChange}
      />
    )

    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-04-01' } })
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ fromDate: '2026-04-01', quickFilter: '' }))
  })
})
