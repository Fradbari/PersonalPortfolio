import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'

interface ToolCall {
  name: string
  args: Record<string, unknown>
  result_summary: string
}

interface QueryResponse {
  answer: string
  tools_used: ToolCall[]
  truncated: boolean
}

export function AiAssistant() {
  const [question, setQuestion] = useState('')

  const queryMutation = useMutation({
    mutationFn: (q: string) => api.post<QueryResponse>('/ai/query', { question: q }),
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!question.trim() || queryMutation.isPending) return
    queryMutation.mutate(question)
  }

  return (
    <div>
      <h2 className="mb-4 text-lg font-semibold">Assistente AI</h2>
      <p className="mb-4 text-sm text-muted-foreground">
        Fai una domanda in linguaggio naturale sulle tue finanze. Ogni domanda è indipendente: non
        viene mantenuta memoria delle domande precedenti.
      </p>

      <form onSubmit={handleSubmit} className="rounded-lg border bg-card p-4">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="es. Quanto ho speso in alimentari negli ultimi 3 mesi?"
          rows={3}
          className="w-full rounded border px-3 py-2 text-sm"
        />
        <div className="mt-3 flex justify-end">
          <Button type="submit" disabled={!question.trim() || queryMutation.isPending}>
            {queryMutation.isPending ? 'Sto pensando...' : 'Chiedi'}
          </Button>
        </div>
      </form>

      {queryMutation.error ? (
        <p className="mt-3 text-destructive">{(queryMutation.error as Error).message}</p>
      ) : null}

      {queryMutation.data ? (
        <div className="mt-6 rounded-lg border bg-card p-4">
          {queryMutation.data.truncated ? (
            <p className="mb-3 rounded border border-warning bg-warning/10 px-3 py-2 text-xs text-warning-foreground">
              Attenzione: la risposta potrebbe essere parziale (dati troncati durante l'elaborazione).
            </p>
          ) : null}

          <h3 className="mb-2 font-semibold">Risposta</h3>
          <p className="whitespace-pre-wrap text-sm">{queryMutation.data.answer}</p>

          <details className="mt-4" open>
            <summary className="cursor-pointer text-sm font-medium text-muted-foreground">
              Tool utilizzati ({queryMutation.data.tools_used.length})
            </summary>
            <ul className="mt-2 space-y-2">
              {queryMutation.data.tools_used.map((tc, i) => (
                <li key={i} className="rounded border px-3 py-2 text-xs">
                  <div className="font-mono font-semibold">{tc.name}</div>
                  <div className="mt-1 text-muted-foreground">
                    args: <code>{JSON.stringify(tc.args)}</code>
                  </div>
                  <div className="mt-1">{tc.result_summary}</div>
                </li>
              ))}
              {queryMutation.data.tools_used.length === 0 ? (
                <li className="text-xs text-muted-foreground">Nessun tool chiamato.</li>
              ) : null}
            </ul>
          </details>
        </div>
      ) : null}
    </div>
  )
}
