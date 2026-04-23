import { useEffect, useRef, useMemo, useState } from 'react'
import api from '../api/client'

const STARTER_MESSAGE = {
  role: 'assistant',
  content: 'Ask about your schedule, availability, or calendar changes. I can answer using your live Google Calendar data and make updates when the request is clear.',
  events: [],
  actions: [],
  mode: null,
  pendingPlan: null,
  starter: true,
}

function actionLabel(action) {
  switch (action?.type) {
    case 'create_event': return 'Created event'
    case 'update_event': return 'Updated event'
    case 'delete_event': return 'Deleted event'
    default: return 'Calendar action'
  }
}

function getChatErrorMessage(err) {
  const status = err?.response?.status
  const detail = err?.response?.data?.detail
  const detailMsg = typeof detail === 'string' ? detail : (detail?.message ?? '')
  if (typeof err?.response?.data?.message === 'string') {
    return err.response.data.message
  }
  // Show the real LLM/server error instead of a generic message
  if (detailMsg) return detailMsg
  if (!err?.response) return 'Cannot reach the backend server. Make sure start.bat is running.'
  if (status === 401) return 'Session expired — please sign in again.'
  if (status === 502) return 'Backend server returned a bad gateway error.'
  if (status === 503) return 'The AI model is unavailable. Check OLLAMA_BASE_URL and model name in backend/.env'
  if (typeof err?.message === 'string') return err.message
  return 'The chatbot request failed.'
}

function formatEventDate(event) {
  const raw = event.start?.dateTime ?? event.start?.date ?? ''
  if (!raw) return ''
  try {
    const d = new Date(raw)
    return d.toLocaleString('en-IN', {
      weekday: 'short', day: 'numeric', month: 'short',
      hour: '2-digit', minute: '2-digit', hour12: true,
    })
  } catch {
    return raw
  }
}

export default function ChatPanel() {
  const [messages, setMessages] = useState([STARTER_MESSAGE])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const history = useMemo(
    () => messages
      .filter((m) => !m.starter)
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .map(({ role, content, events }) => ({ role, content, events: events ?? [] })),
    [messages]
  )

  // Return the pending_plan from the latest assistant turn.
  // The backend ignores stale plans unless the new message is actually a follow-up.
  const lastPendingPlan = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'assistant') return messages[i].pendingPlan ?? null
    }
    return null
  }, [messages])

  const sendMessage = async (message, selectedEventId = null, overridePendingPlan = undefined) => {
    if (!message || loading) return

    const nextMessages = [
      ...messages,
      { role: 'user', content: message, events: [], actions: [], mode: null },
    ]
    setMessages(nextMessages)
    setInput('')
    setLoading(true)
    setError('')

    try {
      const payload = { message, history }
      if (selectedEventId) payload.selected_event_id = selectedEventId
      const planToUse = overridePendingPlan !== undefined ? overridePendingPlan : lastPendingPlan
      if (planToUse) payload.pending_plan = planToUse

      const { data } = await api.post('/chat', payload)

      setMessages([
        ...nextMessages,
        {
          role: 'assistant',
          content: data.answer,
          events: data.events ?? [],
          actions: data.actions ?? [],
          mode: data.mode ?? null,
          pendingPlan: data.pending_plan ?? null,
        },
      ])
    } catch (err) {
      setError(getChatErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    sendMessage(input.trim())
  }

  // Called when user taps an event card in a clarification/disambiguation message
  const handleEventSelect = (event, messageContent) => {
    const date = formatEventDate(event)
    const label = date ? `"${event.title}" on ${date}` : `"${event.title}"`
    sendMessage(`I mean the ${label}`, event.id)
  }

  const handleConfirm = (pendingPlan) => {
    sendMessage('Confirmed', null, pendingPlan)
  }

  const handleCancel = (pendingPlan) => {
    sendMessage('Cancel', null, pendingPlan)
  }

  return (
    <aside className="rounded-3xl border border-gray-800 bg-gray-900/80 shadow-2xl shadow-black/30 backdrop-blur">
      <div className="border-b border-gray-800 px-5 py-4">
        <p className="text-sm font-semibold text-white">Agentic Calendar Chat</p>
        <p className="mt-1 text-xs text-gray-400">RAG over live events plus calendar actions</p>
      </div>

      <div className="max-h-[60vh] space-y-3 overflow-y-auto px-5 py-4">
        {messages.map((message, index) => {
          const isDisambiguation =
            message.role === 'assistant' &&
            message.mode === 'clarification' &&
            message.events?.length > 0

          const isConfirmation =
            message.role === 'assistant' &&
            message.mode === 'confirmation'

          // Only show confirm/cancel on the latest confirmation message
          const isActiveConfirmation = isConfirmation && index === messages.length - 1 && !loading

          return (
            <div key={`${message.role}-${index}`} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[92%] rounded-2xl px-4 py-3 text-sm shadow-lg ${message.role === 'user' ? 'bg-blue-600 text-white' : 'bg-gray-950 text-gray-100 border border-gray-800'}`}>
                <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>

                {message.actions?.length ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {message.actions.map((action, i) => (
                      <span key={`${action.type}-${i}`} className="rounded-full bg-emerald-500/15 px-2.5 py-1 text-[11px] font-medium text-emerald-300">
                        {actionLabel(action)}
                      </span>
                    ))}
                  </div>
                ) : null}

                {message.events?.length ? (
                  <div className="mt-3 rounded-xl bg-white/5 p-3 text-xs text-gray-300">
                    {isDisambiguation ? (
                      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-blue-400">
                        Tap to select
                      </p>
                    ) : (
                      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                        {message.events.length} event{message.events.length !== 1 ? 's' : ''}
                      </p>
                    )}
                    <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
                      {message.events.map((event) => {
                        const dateStr = formatEventDate(event)
                        return isDisambiguation ? (
                          <button
                            key={`${event.calendarId ?? 'primary'}:${event.id}`}
                            type="button"
                            onClick={() => handleEventSelect(event, message.content)}
                            className="w-full text-left rounded-lg border border-blue-500/30 bg-blue-500/10 px-2.5 py-2 transition-colors hover:border-blue-400/60 hover:bg-blue-500/20 focus:outline-none focus:ring-2 focus:ring-blue-500/50 cursor-pointer"
                          >
                            <p className="font-medium text-gray-100">{event.title}</p>
                            {dateStr && <p className="mt-1 text-[11px] text-blue-300">{dateStr}</p>}
                            {event.location && <p className="mt-0.5 text-[11px] text-gray-500">{event.location}</p>}
                          </button>
                        ) : (
                          <div
                            key={`${event.calendarId ?? 'primary'}:${event.id}`}
                            className="rounded-lg border border-white/5 bg-black/20 px-2.5 py-2"
                          >
                            <p className="font-medium text-gray-100">{event.title}</p>
                            {dateStr && <p className="mt-1 text-[11px] text-gray-400">{dateStr}</p>}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                ) : null}

                {isActiveConfirmation ? (
                  <div className="mt-3 flex gap-2">
                    <button
                      type="button"
                      onClick={() => handleConfirm(message.pendingPlan)}
                      className="flex-1 rounded-xl bg-emerald-600 px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
                    >
                      Confirm
                    </button>
                    <button
                      type="button"
                      onClick={() => handleCancel(message.pendingPlan)}
                      className="flex-1 rounded-xl bg-gray-700 px-3 py-2 text-xs font-semibold text-gray-300 transition-colors hover:bg-gray-600 focus:outline-none focus:ring-2 focus:ring-gray-500/50"
                    >
                      Cancel
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
          )
        })}
        {loading ? <p className="text-xs text-gray-500">Thinking through your calendar...</p> : null}
        {error ? <p className="rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-200">{error}</p> : null}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={handleSubmit} className="border-t border-gray-800 px-4 py-4">
        <label htmlFor="calendar-chat-input" className="sr-only">Calendar chat input</label>
        <textarea
          id="calendar-chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              sendMessage(input.trim())
            }
          }}
          rows={3}
          placeholder="Ask things like 'What do I have tomorrow?' or 'Create a meeting with Rahul next Monday at 10 AM.'"
          className="w-full resize-none rounded-2xl border border-gray-700 bg-gray-950 px-4 py-3 text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none"
        />
        <div className="mt-3 flex items-center justify-between gap-3">
          <p className="text-[11px] text-gray-500">Uses retrieved event context and the 1000-question sample set.</p>
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-gray-700 disabled:text-gray-400"
          >
            Send
          </button>
        </div>
      </form>
    </aside>
  )
}
