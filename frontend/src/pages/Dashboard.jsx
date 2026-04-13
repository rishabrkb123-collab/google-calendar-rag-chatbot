import { useState, useEffect, useCallback } from 'react'
import { startOfDay, endOfDay, startOfWeek, endOfWeek, startOfMonth, endOfMonth, addMonths, formatISO } from 'date-fns'
import api from '../api/client'
import Navbar from '../components/Navbar'
import SearchBar from '../components/SearchBar'
import FilterPanel from '../components/FilterPanel'
import EventList from '../components/EventList'

function quickFilterToDates(quickFilter) {
  const now = new Date()
  switch (quickFilter) {
    case 'today':
      return { from: formatISO(startOfDay(now)), to: formatISO(endOfDay(now)) }
    case 'week':
      return { from: formatISO(startOfWeek(now)), to: formatISO(endOfWeek(now)) }
    case 'month':
      return { from: formatISO(startOfMonth(now)), to: formatISO(endOfMonth(now)) }
    case 'upcoming':
      return { from: formatISO(now), to: formatISO(addMonths(now, 3)) }
    default:
      return { from: null, to: null }
  }
}

export default function Dashboard() {
  const [events, setEvents] = useState([])
  const [calendars, setCalendars] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState({
    calendarIds: [],
    fromDate: '',
    toDate: '',
    quickFilter: 'upcoming',
  })

  useEffect(() => {
    api.get('/api/calendars').then(({ data }) => {
      setCalendars(data)
      setFilters((f) => ({ ...f, calendarIds: data.map((c) => c.id) }))
    })
  }, [])

  const fetchEvents = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (search) params.set('q', search)
      if (filters.calendarIds.length === 1) params.set('calendarId', filters.calendarIds[0])

      const dates = filters.quickFilter
        ? quickFilterToDates(filters.quickFilter)
        : { from: filters.fromDate || null, to: filters.toDate || null }

      if (dates.from) params.set('from_date', dates.from)
      if (dates.to) params.set('to_date', dates.to)
      params.set('maxResults', '250')

      const { data } = await api.get(`/api/events?${params.toString()}`)
      setEvents(data.events ?? [])
    } finally {
      setLoading(false)
    }
  }, [search, filters])

  useEffect(() => {
    fetchEvents()
  }, [fetchEvents])

  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <div className="max-w-7xl mx-auto px-6 py-6">
        <div className="mb-6">
          <SearchBar value={search} onChange={setSearch} />
        </div>
        <div className="flex gap-8">
          <FilterPanel calendars={calendars} filters={filters} onChange={setFilters} />
          <main className="flex-1 min-w-0">
            <EventList events={events} calendars={calendars} loading={loading} />
          </main>
        </div>
      </div>
    </div>
  )
}
