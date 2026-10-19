// frontend/src/pages/AiAssistant.tsx
//
// Pagina /assistente-ai (F14, ADR-0032). La sessione corrente vive SOLO
// nell'URL (`?sessione=<id>`, pattern F12): nessun useState parallelo.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { api, ApiError } from '@/lib/api'

interface ToolCall {
  name: string
  args: Record<string, unknown>
  result_summary: string
}

interface QueryResponse {
  answer: string
  tools_used: ToolCall[]
  truncated: boolean
  session_id: number
}

interface SessionSummary {
  id: number
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

interface SessionMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  tools_used: ToolCall[] | null
  truncated: boolean
  created_at: string
}

interface SessionDetail {
  id: number
  title: string
  created_at: string
  updated_at: string
  messages: SessionMessage[]
}

const GONE_NOTICE =
  'Conversazione non più disponibile (es. dopo un restore). Nuova conversazione avviata.'

function formatDate(iso: string): string {
  // Timestamp naive dal backend = UTC: senza suffisso il parser li leggerebbe come locali.
  const hasZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(iso)
  const d = new Date(hasZone ? iso : `${iso}Z`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('it-IT')
}

function ToolTrace({ tools }: { tools: ToolCall[] }) {
  return (
    <div className="mt-3">
      <p className="text-sm font-medium text-muted-foreground">Tool utilizzati ({tools.length})</p>
      <ul className="mt-2 space-y-2">
        {tools.map((tc, i) => (
          <li key={i} className="rounded border px-3 py-2 text-xs">
            <div className="font-mono font-semibold">{tc.name}</div>
            <div className="mt-1 text-muted-foreground">
              args: <code>{JSON.stringify(tc.args)}</code>
            </div>
            <div className="mt-1">{tc.result_summary}</div>
          </li>
        ))}
        {tools.length === 0 ? (
          <li className="text-xs text-muted-foreground">Nessun tool chiamato.</li>
        ) : null}
      </ul>
    </div>
  )
}

export function AiAssistant() {
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [question, setQuestion] = useState('')
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const rawSession = searchParams.get('sessione')
  const parsed = rawSession !== null ? Number(rawSession) : NaN
  const sessionId = Number.isInteger(parsed) && parsed > 0 ? parsed : null

  const setSession = (id: number | null, replace = false) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (id === null) next.delete('sessione')
        else next.set('sessione', String(id))
        return next
      },
      { replace },
    )
  }

  const sessionsQuery = useQuery({
    queryKey: ['ai', 'sessions'],
    queryFn: () => api.get<{ sessions: SessionSummary[] }>('/ai/sessions'),
  })

  const detailQuery = useQuery({
    queryKey: ['ai', 'sessions', sessionId],
    queryFn: () => api.get<SessionDetail>(`/ai/sessions/${sessionId}`),
    enabled: sessionId !== null,
    retry: false,
  })

  const invalidate = (id: number | null) => {
    const jobs = [queryClient.invalidateQueries({ queryKey: ['ai', 'sessions'], exact: true })]
    if (id !== null) jobs.push(queryClient.invalidateQueries({ queryKey: ['ai', 'sessions', id] }))
    return Promise.all(jobs)
  }

  // Sessione cancellata: il dettaglio si rimuove dalla cache (un invalidate lo
  // rifetcherebbe con 404 prima che l'URL aggiornato disabiliti la query).
  const dropDetail = (id?: number) =>
    queryClient.removeQueries({
      queryKey: id === undefined ? ['ai', 'sessions'] : ['ai', 'sessions', id],
      predicate: (q) => q.queryKey.length === 3,
    })

  // Sessione visualizzata ora: una risposta tardiva non deve spostare l'utente
  // se nel frattempo ha cambiato conversazione.
  const currentSession = useRef(sessionId)
  currentSession.current = sessionId

  // 404 sul GET dettaglio (es. dopo un restore): sessione fuori dall'URL + avviso.
  const detailError = detailQuery.error
  const detailGone = detailError instanceof ApiError && detailError.status === 404
  useEffect(() => {
    if (!detailGone) return
    setNotice(GONE_NOTICE)
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.delete('sessione')
        return next
      },
      { replace: true },
    )
    void queryClient.invalidateQueries({ queryKey: ['ai', 'sessions'] })
  }, [detailGone, setSearchParams, queryClient])

  const queryMutation = useMutation({
    mutationFn: ({ q, from }: { q: string; from: number | null }) =>
      api.post<QueryResponse>('/ai/query', {
        question: q,
        ...(from !== null ? { session_id: from } : {}),
      }),
    onSuccess: async (data, vars) => {
      if (currentSession.current === vars.from) {
        setNotice(null)
        setQuestion('')
        setSession(data.session_id)
      }
      await invalidate(data.session_id)
    },
    onError: (err, vars) => {
      if (err instanceof ApiError && err.status === 404) {
        if (vars.from !== null) dropDetail(vars.from)
        if (currentSession.current === vars.from) {
          setNotice(GONE_NOTICE)
          setSession(null, true)
        }
        void invalidate(null)
      }
    },
    onSettled: () => setPendingQuestion(null),
  })

  const deleteOne = useMutation({
    mutationFn: (id: number) => api.delete<void>(`/ai/sessions/${id}`),
    onSuccess: async (_d, id) => {
      if (id === currentSession.current) setSession(null)
      dropDetail(id)
      await invalidate(null)
    },
  })

  const deleteAll = useMutation({
    mutationFn: () =>
      api.delete<{ deleted_sessions: number; deleted_messages: number }>('/ai/sessions', {
        confirm: true,
      }),
    onSuccess: async () => {
      setSession(null)
      dropDetail()
      await invalidate(null)
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const q = question.trim()
    if (!q || queryMutation.isPending) return
    setPendingQuestion(q)
    queryMutation.mutate({ q, from: sessionId })
  }

  const newConversation = () => {
    setNotice(null)
    setQuestion('')
    setSession(null)
  }

  const sessions = sessionsQuery.data?.sessions ?? []
  const messages = detailQuery.data?.messages ?? []
  const mutationError =
    queryMutation.error &&
    !(queryMutation.error instanceof ApiError && queryMutation.error.status === 404)
      ? (queryMutation.error as Error).message
      : null

  return (
    <div>
      <h2 className="mb-4 text-lg font-semibold">Assistente AI</h2>
      <p className="mb-4 text-sm text-muted-foreground">
        Fai una domanda in linguaggio naturale sulle tue finanze. Le conversazioni sono salvate in
        locale e le ultime N coppie di messaggi (impostazione «Turni massimi di cronologia») vengono
        rinviate al provider a ogni domanda. Dettagli in SECURITY.md.
      </p>

      <div className="grid gap-6 md:grid-cols-[16rem_1fr]">
        <aside className="space-y-3">
          <Button className="w-full" onClick={newConversation}>
            Nuova conversazione
          </Button>
          <ul className="space-y-2">
            {sessions.map((s) => (
              <li
                key={s.id}
                className={`flex items-start justify-between gap-2 rounded border px-3 py-2 text-sm ${
                  s.id === sessionId ? 'border-primary bg-muted' : 'bg-card'
                }`}
              >
                <button
                  type="button"
                  onClick={() => {
                    setNotice(null)
                    setSession(s.id)
                  }}
                  className="min-w-0 flex-1 text-left"
                >
                  <span className="block truncate font-medium">{s.title}</span>
                  <span className="block text-xs text-muted-foreground">
                    {formatDate(s.updated_at)}
                  </span>
                </button>
                <button
                  type="button"
                  aria-label={`Elimina conversazione ${s.title}`}
                  onClick={() => deleteOne.mutate(s.id)}
                  disabled={deleteOne.isPending}
                  className="shrink-0 rounded px-1 text-muted-foreground hover:text-destructive"
                >
                  ✕
                </button>
              </li>
            ))}
            {sessions.length === 0 && !sessionsQuery.isLoading ? (
              <li className="text-xs text-muted-foreground">Nessuna conversazione salvata.</li>
            ) : null}
          </ul>
          {sessionsQuery.error ? (
            <p className="text-xs text-destructive">{(sessionsQuery.error as Error).message}</p>
          ) : null}
          {deleteOne.error ? (
            <p className="text-xs text-destructive">{(deleteOne.error as Error).message}</p>
          ) : null}

          {sessions.length > 0 ? (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="destructive" size="sm" className="w-full">
                  Azzera storico
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogTitle>Azzerare tutto lo storico?</AlertDialogTitle>
                <AlertDialogDescription>
                  Cancella tutte le conversazioni salvate e i loro messaggi. Operazione distruttiva
                  e non reversibile (ADR-0032).
                </AlertDialogDescription>
                <div className="mt-4 flex justify-end gap-2">
                  <AlertDialogCancel asChild>
                    <Button variant="outline">Annulla</Button>
                  </AlertDialogCancel>
                  <AlertDialogAction asChild>
                    <Button variant="destructive" onClick={() => deleteAll.mutate()}>
                      Conferma azzeramento
                    </Button>
                  </AlertDialogAction>
                </div>
              </AlertDialogContent>
            </AlertDialog>
          ) : null}
          {deleteAll.error ? (
            <p className="text-xs text-destructive">{(deleteAll.error as Error).message}</p>
          ) : null}
        </aside>

        <section className="min-w-0">
          {notice ? (
            <p className="mb-3 rounded border border-warning bg-warning/10 px-3 py-2 text-sm text-warning-foreground">
              {notice}
            </p>
          ) : null}

          <div className="space-y-4">
            {detailQuery.isLoading ? <p className="text-sm">Caricamento...</p> : null}
            {detailError && !detailGone ? (
              <p className="text-destructive">{(detailError as Error).message}</p>
            ) : null}

            {messages.map((m) =>
              m.role === 'user' ? (
                <div key={m.id} className="rounded-lg border bg-muted p-4">
                  <p className="mb-1 text-xs font-medium text-muted-foreground">Tu</p>
                  <p className="whitespace-pre-wrap text-sm">{m.content}</p>
                </div>
              ) : (
                <div key={m.id} className="rounded-lg border bg-card p-4">
                  {m.truncated ? (
                    <p className="mb-3 rounded border border-warning bg-warning/10 px-3 py-2 text-xs text-warning-foreground">
                      Attenzione: la risposta potrebbe essere parziale (dati troncati durante
                      l'elaborazione).
                    </p>
                  ) : null}
                  <h3 className="mb-2 font-semibold">Risposta</h3>
                  <p className="whitespace-pre-wrap text-sm">{m.content}</p>
                  <ToolTrace tools={m.tools_used ?? []} />
                </div>
              ),
            )}

            {pendingQuestion && queryMutation.variables?.from === sessionId ? (
              <div className="rounded-lg border bg-muted p-4">
                <p className="mb-1 text-xs font-medium text-muted-foreground">Tu</p>
                <p className="whitespace-pre-wrap text-sm">{pendingQuestion}</p>
              </div>
            ) : null}
          </div>

          <form onSubmit={handleSubmit} className="mt-4 rounded-lg border bg-card p-4">
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="es. Quanto ho speso in alimentari negli ultimi 3 mesi?"
              rows={3}
              className="w-full rounded border bg-background px-3 py-2 text-sm text-foreground"
            />
            <div className="mt-3 flex justify-end">
              <Button type="submit" disabled={!question.trim() || queryMutation.isPending}>
                {queryMutation.isPending ? 'Sto pensando...' : 'Chiedi'}
              </Button>
            </div>
          </form>

          {mutationError ? <p className="mt-3 text-destructive">{mutationError}</p> : null}
        </section>
      </div>
    </div>
  )
}
