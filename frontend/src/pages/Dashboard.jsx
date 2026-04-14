import { useState, useEffect, useCallback } from 'react'
import { startOfDay, endOfDay, startOfWeek, endOfWeek, startOfMonth, endOfMonth, formatISO } from 'date-fns'
import api from '../api/client'
import Navbar from '../components/Navbar'
import SearchBar from '../components/SearchBar'
import FilterPanel from '../components/FilterPanel'
import EventList from '../components/EventList'
import ChatPanel from '../components/ChatPanel'
import EventDetailsModal from '../components/EventDetailsModal'

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
      return { from: formatISO(now), to: null }
    case 'all':
    default:
      return { from: null, to: null }
  }
}

function getEventStartValue(event) {
  return event.start?.dateTime ?? event.start?.date ?? ''
}

export default function Dashboard() {
  const [events, setEvents] = useState([])
  const [calendars, setCalendars] = useState([])
  const [calendarsLoaded, setCalendarsLoaded] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [modalState, setModalState] = useState(null)
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState({
    calendarIds: [],
    fromDate: '',
    toDate: '',
    quickFilter: 'all',
  })

  const getErrorPayload = (err) => {
    const detail = err?.response?.data?.detail
    if (typeof detail === 'string') return { message: detail }
    if (detail?.message) return detail
    return { message: 'Failed to load Google Calendar data.' }
  }

  useEffect(() => {
    api.get('/api/calendars')
      .then(({ data }) => {
        setCalendars(data)
        const defaultCalendarIds = data
          .filter((calendar) => !calendar.isHoliday && !calendar.isBirthday)
          .map((calendar) => calendar.id)
        setFilters((f) => ({
          ...f,
          calendarIds: defaultCalendarIds.length ? defaultCalendarIds : data.map((c) => c.id),
        }))
        setCalendarsLoaded(true)
        setError(null)
      })
      .catch((err) => {
        setCalendars([])
        setCalendarsLoaded(true)
        setError(getErrorPayload(err))
      })
  }, [])

  const fetchEvents = useCallback(async () => {
    if (!calendarsLoaded) return

    if (!filters.calendarIds.length) {
      setEvents([])
      setLoading(false)
      return
    }

    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (search) params.set('q', search)

      const dates = filters.quickFilter
        ? quickFilterToDates(filters.quickFilter)
        : { from: filters.fromDate || null, to: filters.toDate || null }

      if (dates.from) params.set('from_date', dates.from)
      if (dates.to) params.set('to_date', dates.to)
      params.set('maxResults', '250')
      if (filters.calendarIds.length && filters.calendarIds.length !== calendars.length) {
        params.set('calendarIds', filters.calendarIds.join(','))
      }

      const { data } = await api.get(`/api/events/all?${params.toString()}`)
      const mergedEvents = (data.events ?? []).sort((a, b) => getEventStartValue(a).localeCompare(getEventStartValue(b)))

      setEvents(mergedEvents)
      setError(null)
    } catch (err) {
      setEvents([])
      setError(getErrorPayload(err))
    } finally {
      setLoading(false)
    }
  }, [calendars.length, calendarsLoaded, filters, search])

  useEffect(() => {
    fetchEvents()
  }, [fetchEvents])

  const openModal = (mode, event) => setModalState({ mode, event })

  const handleDeleteEvent = async (event) => {
    const confirmed = window.confirm(`Delete "${event.title}"?`)
    if (!confirmed) return

    try {
      await api.delete(`/api/event?calendarId=${encodeURIComponent(event.calendarId)}&eventId=${encodeURIComponent(event.id)}`)
      await fetchEvents()
    } catch (err) {
      setError(getErrorPayload(err))
    }
  }

  const handleEventSaved = async () => {
    setModalState(null)
    await fetchEvents()
  }

  const handleEventDeleted = async () => {
    setModalState(null)
    await fetchEvents()
  }

  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <div className="max-w-7xl mx-auto px-6 py-6">
        <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="flex-1">
            <SearchBar value={search} onChange={setSearch} />
          </div>
          <button
            type="button"
            onClick={fetchEvents}
            disabled={loading || !calendarsLoaded}
            className="inline-flex items-center justify-center rounded-xl border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-medium text-gray-200 transition-colors hover:border-blue-500 hover:text-white disabled:cursor-not-allowed disabled:border-gray-800 disabled:text-gray-500"
          >
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
        <div className="flex gap-8">
          <FilterPanel calendars={calendars} filters={filters} onChange={setFilters} />
          <div className="flex-1 min-w-0 grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
            <main className="min-w-0">
              <EventList
                events={events}
                calendars={calendars}
                loading={loading}
                error={error}
                onViewEvent={(event) => openModal('view', event)}
                onEditEvent={(event) => openModal('edit', event)}
                onDeleteEvent={handleDeleteEvent}
              />
            </main>
            <ChatPanel />
          </div>
        </div>
      </div>
      {modalState ? (
        <EventDetailsModal
          event={modalState.event}
          mode={modalState.mode}
          onClose={() => setModalState(null)}
          onEventSaved={handleEventSaved}
          onEventDeleted={handleEventDeleted}
        />
      ) : null}
    </div>
  )
}
