import { useEffect, useMemo, useState } from 'react'
import api from '../api/client'

function toLocalDateTimeInput(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (part) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function fromLocalDateTimeInput(value) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toISOString()
}

function buildInitialForm(event) {
  return {
    title: event?.title ?? '',
    allDay: Boolean(event?.allDay),
    startDate: event?.start?.date ?? '',
    endDate: event?.end?.date ?? '',
    startDateTime: toLocalDateTimeInput(event?.start?.dateTime),
    endDateTime: toLocalDateTimeInput(event?.end?.dateTime),
    description: event?.description ?? '',
    location: event?.location ?? '',
    visibility: event?.visibility ?? 'default',
    attendeeEmails: (event?.attendees ?? []).map((attendee) => attendee.email).filter(Boolean).join(', '),
    recurrence: (event?.recurrence ?? []).join('\n'),
    reminderMinutes: (event?.reminders?.overrides ?? []).map((override) => override.minutes).join(', '),
  }
}

function buildRequestBody(form) {
  const body = {
    summary: form.title,
    description: form.description,
    location: form.location,
    visibility: form.visibility,
  }

  if (form.allDay) {
    body.start = { date: form.startDate }
    body.end = { date: form.endDate || form.startDate }
  } else {
    body.start = { dateTime: fromLocalDateTimeInput(form.startDateTime) }
    body.end = { dateTime: fromLocalDateTimeInput(form.endDateTime) }
  }

  const attendeeEmails = form.attendeeEmails
    .split(',')
    .map((email) => email.trim())
    .filter(Boolean)
  body.attendees = attendeeEmails.map((email) => ({ email }))

  const recurrence = form.recurrence
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  body.recurrence = recurrence

  const reminderMinutes = form.reminderMinutes
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean)
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value))

  body.reminders = reminderMinutes.length
    ? {
        useDefault: false,
        overrides: reminderMinutes.map((minutes) => ({ method: 'popup', minutes })),
      }
    : { useDefault: true }

  return body
}

function getErrorMessage(err, fallback) {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  if (typeof err?.message === 'string') return err.message
  return fallback
}

export default function EventDetailsModal({ event, mode, onClose, onEventSaved, onEventDeleted }) {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState(event)
  const [form, setForm] = useState(() => buildInitialForm(event))

  const readOnly = mode === 'view'
  const title = readOnly ? 'View Event' : 'Edit Event'

  useEffect(() => {
    let active = true

    const loadEvent = async () => {
      setLoading(true)
      setError('')
      try {
        const { data } = await api.get(`/api/event?calendarId=${encodeURIComponent(event.calendarId)}&eventId=${encodeURIComponent(event.id)}`)
        if (!active) return
        setDetail(data)
        setForm(buildInitialForm(data))
      } catch (err) {
        if (!active) return
        setError(getErrorMessage(err, 'Failed to load event details.'))
      } finally {
        if (active) setLoading(false)
      }
    }

    loadEvent()
    return () => {
      active = false
    }
  }, [event])

  const canSubmit = useMemo(() => {
    if (readOnly) return false
    if (form.allDay) return Boolean(form.title.trim() && form.startDate && form.endDate)
    return Boolean(form.title.trim() && form.startDateTime && form.endDateTime)
  }, [form, readOnly])

  const updateField = (field, value) => {
    setForm((current) => ({ ...current, [field]: value }))
  }

  const handleSave = async (submitEvent) => {
    submitEvent.preventDefault()
    if (!canSubmit) return

    setSaving(true)
    setError('')
    try {
      const { data } = await api.patch(
        `/api/event?calendarId=${encodeURIComponent(event.calendarId)}&eventId=${encodeURIComponent(event.id)}`,
        { body: buildRequestBody(form) }
      )
      onEventSaved(data)
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to update the event.'))
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    const confirmed = window.confirm(`Delete "${detail?.title ?? event.title}"?`)
    if (!confirmed) return

    setSaving(true)
    setError('')
    try {
      await api.delete(`/api/event?calendarId=${encodeURIComponent(event.calendarId)}&eventId=${encodeURIComponent(event.id)}`)
      onEventDeleted(event)
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to delete the event.'))
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 px-4 py-8">
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-3xl border border-gray-800 bg-gray-950 shadow-2xl shadow-black/50">
        <div className="flex items-center justify-between border-b border-gray-800 px-6 py-4">
          <div>
            <p className="text-base font-semibold text-white">{title}</p>
            <p className="mt-1 text-xs text-gray-500">{event.calendarId}</p>
          </div>
          <button onClick={onClose} className="rounded-xl px-3 py-2 text-sm text-gray-400 hover:bg-gray-900 hover:text-white">Close</button>
        </div>

        {loading ? (
          <div className="overflow-y-auto px-6 py-10 text-sm text-gray-400">Loading event details...</div>
        ) : (
          <form onSubmit={handleSave} className="space-y-5 overflow-y-auto px-6 py-6">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="md:col-span-2">
                <label htmlFor="event-title" className="mb-1 block text-xs text-gray-500">Title</label>
                <input id="event-title" value={form.title} onChange={(e) => updateField('title', e.target.value)} readOnly={readOnly} className="w-full rounded-xl border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none read-only:opacity-80" />
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-300">
                <input type="checkbox" checked={form.allDay} disabled={readOnly} onChange={(e) => updateField('allDay', e.target.checked)} />
                All day
              </label>
              <div>
                <label htmlFor="event-visibility" className="mb-1 block text-xs text-gray-500">Visibility</label>
                <select id="event-visibility" value={form.visibility} onChange={(e) => updateField('visibility', e.target.value)} disabled={readOnly} className="w-full rounded-xl border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none">
                  <option value="default">Default</option>
                  <option value="public">Public</option>
                  <option value="private">Private</option>
                  <option value="confidential">Confidential</option>
                </select>
              </div>
              {form.allDay ? (
                <>
                  <div>
                    <label htmlFor="event-start-date" className="mb-1 block text-xs text-gray-500">Start Date</label>
                    <input id="event-start-date" type="date" value={form.startDate} onChange={(e) => updateField('startDate', e.target.value)} readOnly={readOnly} className="w-full rounded-xl border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" />
                  </div>
                  <div>
                    <label htmlFor="event-end-date" className="mb-1 block text-xs text-gray-500">End Date</label>
                    <input id="event-end-date" type="date" value={form.endDate} onChange={(e) => updateField('endDate', e.target.value)} readOnly={readOnly} className="w-full rounded-xl border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" />
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <label htmlFor="event-start-datetime" className="mb-1 block text-xs text-gray-500">Start</label>
                    <input id="event-start-datetime" type="datetime-local" value={form.startDateTime} onChange={(e) => updateField('startDateTime', e.target.value)} readOnly={readOnly} className="w-full rounded-xl border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" />
                  </div>
                  <div>
                    <label htmlFor="event-end-datetime" className="mb-1 block text-xs text-gray-500">End</label>
                    <input id="event-end-datetime" type="datetime-local" value={form.endDateTime} onChange={(e) => updateField('endDateTime', e.target.value)} readOnly={readOnly} className="w-full rounded-xl border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" />
                  </div>
                </>
              )}
              <div className="md:col-span-2">
                <label htmlFor="event-location" className="mb-1 block text-xs text-gray-500">Location</label>
                <input id="event-location" value={form.location} onChange={(e) => updateField('location', e.target.value)} readOnly={readOnly} className="w-full rounded-xl border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" />
              </div>
              <div className="md:col-span-2">
                <label htmlFor="event-description" className="mb-1 block text-xs text-gray-500">Description</label>
                <textarea id="event-description" rows={4} value={form.description} onChange={(e) => updateField('description', e.target.value)} readOnly={readOnly} className="w-full rounded-xl border border-gray-700 bg-gray-900 px-4 py-3 text-sm text-white focus:border-blue-500 focus:outline-none" />
              </div>
              <div className="md:col-span-2">
                <label htmlFor="event-attendees" className="mb-1 block text-xs text-gray-500">Attendees (comma separated emails)</label>
                <textarea id="event-attendees" rows={2} value={form.attendeeEmails} onChange={(e) => updateField('attendeeEmails', e.target.value)} readOnly={readOnly} className="w-full rounded-xl border border-gray-700 bg-gray-900 px-4 py-3 text-sm text-white focus:border-blue-500 focus:outline-none" />
              </div>
              <div className="md:col-span-2">
                <label htmlFor="event-recurrence" className="mb-1 block text-xs text-gray-500">Recurrence (one RRULE per line)</label>
                <textarea id="event-recurrence" rows={2} value={form.recurrence} onChange={(e) => updateField('recurrence', e.target.value)} readOnly={readOnly} className="w-full rounded-xl border border-gray-700 bg-gray-900 px-4 py-3 text-sm text-white focus:border-blue-500 focus:outline-none" />
              </div>
              <div className="md:col-span-2">
                <label htmlFor="event-reminders" className="mb-1 block text-xs text-gray-500">Reminder Minutes (comma separated)</label>
                <input id="event-reminders" value={form.reminderMinutes} onChange={(e) => updateField('reminderMinutes', e.target.value)} readOnly={readOnly} className="w-full rounded-xl border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" />
              </div>
            </div>

            {error ? <p className="rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-200">{error}</p> : null}

            <div className="flex items-center justify-between gap-3 border-t border-gray-800 pt-4">
              <div className="flex items-center gap-3">
                {detail?.link ? <a href={detail.link} target="_blank" rel="noreferrer" className="text-sm text-blue-300 underline underline-offset-4">Open in Google Calendar</a> : null}
              </div>
              <div className="flex items-center gap-3">
                <button type="button" onClick={handleDelete} disabled={saving} className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm font-medium text-red-200 hover:bg-red-500/20 disabled:opacity-50">Delete</button>
                {!readOnly ? <button type="submit" disabled={!canSubmit || saving} className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-50">Save Changes</button> : null}
              </div>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
