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
})
