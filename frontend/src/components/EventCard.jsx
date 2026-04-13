import { motion } from 'framer-motion'
import { format, parseISO } from 'date-fns'

function formatEventTime(event) {
  if (event.allDay) {
    const date = event.start.date
    return format(parseISO(date), 'MMM d, yyyy') + ' · All day'
  }
  const start = parseISO(event.start.dateTime)
  const end = parseISO(event.end.dateTime)
  return `${format(start, 'MMM d, yyyy')} · ${format(start, 'h:mm a')} – ${format(end, 'h:mm a')}`
}

export default function EventCard({ event, calendarColor = '#4285F4', index = 0 }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: index * 0.03 }}
      className="bg-gray-900 border border-gray-800 rounded-xl p-4 hover:border-gray-600 transition-colors group"
    >
      <div className="flex items-start gap-3">
        <div
          className="w-1 rounded-full flex-shrink-0 mt-1 self-stretch min-h-[2rem]"
          style={{ backgroundColor: calendarColor }}
        />
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-white text-sm leading-snug truncate group-hover:text-blue-300 transition-colors">
            {event.title}
          </h3>
          <p className="text-gray-400 text-xs mt-1">
            {formatEventTime(event)}
          </p>
          {event.location && (
            <div className="flex items-center gap-1 mt-1.5">
              <svg className="w-3 h-3 text-gray-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
              <span className="text-gray-500 text-xs truncate">{event.location}</span>
            </div>
          )}
          {event.description && (
            <p className="text-gray-600 text-xs mt-1.5 line-clamp-2">{event.description}</p>
          )}
        </div>
      </div>
    </motion.div>
  )
}
