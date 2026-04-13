import { motion } from 'framer-motion'

const QUICK_FILTERS = [
  { label: 'Today', value: 'today' },
  { label: 'This Week', value: 'week' },
  { label: 'This Month', value: 'month' },
  { label: 'Upcoming', value: 'upcoming' },
]

export default function FilterPanel({ calendars, filters, onChange }) {
  const toggleCalendar = (calId) => {
    const current = filters.calendarIds ?? []
    const updated = current.includes(calId)
      ? current.filter((id) => id !== calId)
      : [...current, calId]
    onChange({ ...filters, calendarIds: updated })
  }

  const setQuickFilter = (value) => {
    onChange({ ...filters, quickFilter: filters.quickFilter === value ? '' : value })
  }

  const setDate = (key, val) => {
    onChange({ ...filters, [key]: val })
  }

  return (
    <motion.aside
      initial={{ x: -20, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      transition={{ duration: 0.3 }}
      className="w-64 flex-shrink-0 space-y-6"
    >
      <div>
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Quick Filters</h3>
        <div className="flex flex-wrap gap-2">
          {QUICK_FILTERS.map(({ label, value }) => (
            <button
              key={value}
              onClick={() => setQuickFilter(value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                filters.quickFilter === value
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div>
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Date Range</h3>
        <div className="space-y-2">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">From</label>
            <input
              type="date"
              value={filters.fromDate}
              onChange={(e) => setDate('fromDate', e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500 [color-scheme:dark]"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">To</label>
            <input
              type="date"
              value={filters.toDate}
              onChange={(e) => setDate('toDate', e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500 [color-scheme:dark]"
            />
          </div>
        </div>
      </div>

      <div>
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Calendars</h3>
        <div className="space-y-2">
          {calendars.map((cal) => (
            <label key={cal.id} htmlFor={`cal-${cal.id}`} className="flex items-center gap-2.5 cursor-pointer group">
              <input
                type="checkbox"
                id={`cal-${cal.id}`}
                checked={(filters.calendarIds ?? []).includes(cal.id)}
                onChange={() => toggleCalendar(cal.id)}
                className="sr-only"
                aria-label={cal.name}
              />
              <div
                onClick={() => toggleCalendar(cal.id)}
                className="w-4 h-4 rounded flex items-center justify-center border-2 flex-shrink-0 cursor-pointer transition-colors"
                style={{
                  backgroundColor: (filters.calendarIds ?? []).includes(cal.id) ? cal.color : 'transparent',
                  borderColor: cal.color,
                }}
              >
                {(filters.calendarIds ?? []).includes(cal.id) && (
                  <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                  </svg>
                )}
              </div>
              <span className="text-xs text-gray-300 group-hover:text-white transition-colors truncate">
                {cal.name}
              </span>
            </label>
          ))}
        </div>
      </div>
    </motion.aside>
  )
}
