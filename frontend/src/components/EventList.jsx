import { motion, AnimatePresence } from 'framer-motion'
import EventCard from './EventCard'

function getCalendarColor(event, calendars) {
  const cal = calendars.find((c) => c.id === event.calendarId)
  return cal?.color ?? '#4285F4'
}

export default function EventList({ events, calendars, loading, error, onViewEvent, onEditEvent, onDeleteEvent }) {
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-gray-500">
        <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mb-4" />
        <p className="text-sm">Loading events...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 px-6 py-5 text-amber-50 shadow-lg shadow-amber-950/20">
        <p className="text-sm font-semibold text-amber-200">Calendar data could not be loaded</p>
        <p className="mt-2 text-sm text-amber-50/90">{error.message}</p>
        {error.resolution ? <p className="mt-2 text-xs text-amber-100/80">{error.resolution}</p> : null}
        {error.setupUrl ? (
          <a
            href={error.setupUrl}
            target="_blank"
            rel="noreferrer"
            className="mt-3 inline-flex text-xs font-medium text-amber-200 underline underline-offset-4"
          >
            Open Google Cloud API setup
          </a>
        ) : null}
      </div>
    )
  }

  if (!events.length) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-gray-600">
        <svg className="w-16 h-16 mb-4 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1}
            d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
        <p className="text-sm font-medium">No events found</p>
        <p className="text-xs mt-1 text-gray-700">Try adjusting your search or filters</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-gray-600 mb-3">{events.length} event{events.length !== 1 ? 's' : ''}</p>
      <AnimatePresence>
        {events.map((event, index) => (
          <EventCard
            key={`${event.calendarId ?? 'primary'}:${event.id}`}
            event={event}
            calendarColor={getCalendarColor(event, calendars)}
            index={index}
            onView={onViewEvent}
            onEdit={onEditEvent}
            onDelete={onDeleteEvent}
          />
        ))}
      </AnimatePresence>
    </div>
  )
}
