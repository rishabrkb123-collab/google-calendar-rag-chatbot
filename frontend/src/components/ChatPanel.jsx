import { useMemo, useState } from 'react'
import api from '../api/client'

const STARTER_MESSAGE = {
  role: 'assistant',
  content: 'Ask about your schedule, availability, or calendar changes. I can answer using your live Google Calendar data and make updates when the request is clear.',
  events: [],
  actions: [],
  starter: true,
}

function actionLabel(action) {
  switch (action?.type) {
    case 'create_event':
      return 'Created event'
    case 'update_event':
      return 'Updated event'
    case 'delete_event':
      return 'Deleted event'
    default:
      return 'Calendar action'
  }
}

function getChatErrorMessage(err) {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  if (typeof err?.response?.data?.message === 'string') return err.response.data.message
  if (typeof err?.message === 'string') return err.message
  return 'The chatbot request failed.'
}

export default function ChatPanel() {
  const [messages, setMessages] = useState([STARTER_MESSAGE])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const history = useMemo(
    () => messages
      .filter((message) => !message.starter)
      .filter((message) => message.role === 'user' || message.role === 'assistant')
      .map(({ role, content, events }) => ({ role, content, events: events ?? [] })),
    [messages]
  )

  const handleSubmit = async (event) => {
    event.preventDefault()
    const message = input.trim()
    if (!message || loading) return

    const nextMessages = [...messages, { role: 'user', content: message, events: [], actions: [] }]
    setMessages(nextMessages)
    setInput('')
    setLoading(true)
    setError('')

    try {
      const { data } = await api.post('/chat', {
        message,
        history,
      })

      setMessages([
        ...nextMessages,
        {
          role: 'assistant',
          content: data.answer,
          events: data.events ?? [],
          actions: data.actions ?? [],
        },
      ])
    } catch (err) {
      setError(getChatErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <aside className="rounded-3xl border border-gray-800 bg-gray-900/80 shadow-2xl shadow-black/30 backdrop-blur">
      <div className="border-b border-gray-800 px-5 py-4">
        <p className="text-sm font-semibold text-white">Agentic Calendar Chat</p>
        <p className="mt-1 text-xs text-gray-400">RAG over live events plus calendar actions</p>
      </div>

      <div className="max-h-[60vh] space-y-3 overflow-y-auto px-5 py-4">
        {messages.map((message, index) => (
          <div key={`${message.role}-${index}`} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[92%] rounded-2xl px-4 py-3 text-sm shadow-lg ${message.role === 'user' ? 'bg-blue-600 text-white' : 'bg-gray-950 text-gray-100 border border-gray-800'}`}>
              <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>
              {message.actions?.length ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  {message.actions.map((action, actionIndex) => (
                    <span key={`${action.type}-${actionIndex}`} className="rounded-full bg-emerald-500/15 px-2.5 py-1 text-[11px] font-medium text-emerald-300">
                      {actionLabel(action)}
                    </span>
                  ))}
                </div>
              ) : null}
              {message.events?.length ? (
                <div className="mt-3 rounded-xl bg-white/5 p-3 text-xs text-gray-300">
                  <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                    {message.events.length} event{message.events.length !== 1 ? 's' : ''}
                  </p>
                  <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
                    {message.events.map((event) => (
                      <div key={`${event.calendarId ?? 'primary'}:${event.id}`} className="rounded-lg border border-white/5 bg-black/20 px-2.5 py-2">
                        <p className="font-medium text-gray-100">{event.title}</p>
                        <p className="mt-1 text-[11px] text-gray-400">{event.start?.dateTime ?? event.start?.date ?? ''}</p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        ))}
        {loading ? <p className="text-xs text-gray-500">Thinking through your calendar...</p> : null}
        {error ? <p className="rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-200">{error}</p> : null}
      </div>

      <form onSubmit={handleSubmit} className="border-t border-gray-800 px-4 py-4">
        <label htmlFor="calendar-chat-input" className="sr-only">Calendar chat input</label>
        <textarea
          id="calendar-chat-input"
          value={input}
          onChange={(event) => setInput(event.target.value)}
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
