import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
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
import { api } from '@/lib/api'

interface Transaction {
  id: number
  date: string
  amount: number
  currency: string
  type: string
  category_id: number | null
  category_raw: string
  account: string
  comment: string | null
  tag: string | null
  source: string
}

interface TransactionsResponse {
  items: Transaction[]
  total: number
  page: number
  page_size: number
}

interface Category {
  id: number
  name: string
}

export function Transactions() {
  const [yearMonth, setYearMonth] = useState('')
  const [type, setType] = useState('')
  const [page, setPage] = useState(1)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editComment, setEditComment] = useState('')
  const [editTag, setEditTag] = useState('')
  const [editCategoryId, setEditCategoryId] = useState('')

  const queryClient = useQueryClient()

  const params = new URLSearchParams()
  if (yearMonth) params.set('year_month', yearMonth)
  if (type) params.set('type', type)
  params.set('page', String(page))

  const { data, isLoading } = useQuery<TransactionsResponse>({
    queryKey: ['transactions', yearMonth, type, page],
    queryFn: () => api.get<TransactionsResponse>(`/transactions?${params.toString()}`),
  })

  const { data: categories } = useQuery<Category[]>({
    queryKey: ['categories'],
    queryFn: () => api.get<Category[]>('/categories'),
  })

  const updateMutation = useMutation({
    mutationFn: (vars: { id: number; body: Record<string, unknown> }) =>
      api.put(`/transactions/${vars.id}`, vars.body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transactions'] })
      setEditingId(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/transactions/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['transactions'] }),
  })

  function startEdit(t: Transaction) {
    setEditingId(t.id)
    setEditComment(t.comment ?? '')
    setEditTag(t.tag ?? '')
    setEditCategoryId(t.category_id ? String(t.category_id) : '')
  }

  function saveEdit(id: number) {
    updateMutation.mutate({
      id,
      body: {
        comment: editComment || null,
        tag: editTag || null,
        category_id: editCategoryId ? Number(editCategoryId) : null,
      },
    })
  }

  if (isLoading) return <p>Caricamento...</p>

  return (
    <div>
      <h2 className="mb-4 text-lg font-semibold">Transazioni</h2>
      <div className="mb-4 flex gap-3">
        <input
          type="month"
          value={yearMonth}
          onChange={(e) => {
            setYearMonth(e.target.value)
            setPage(1)
          }}
          className="rounded border px-2 py-1 text-sm"
        />
        <select
          value={type}
          onChange={(e) => {
            setType(e.target.value)
            setPage(1)
          }}
          className="rounded border px-2 py-1 text-sm"
        >
          <option value="">Tutti i tipi</option>
          <option value="expense">Uscite</option>
          <option value="income">Entrate</option>
        </select>
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="py-2">Data</th>
            <th>Importo</th>
            <th>Tipo</th>
            <th>Categoria</th>
            <th>Conto</th>
            <th>Commento</th>
            <th>Tag</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {data?.items.map((t) => (
            <tr key={t.id} className="border-b">
              <td className="py-2">{t.date.slice(0, 10)}</td>
              <td className={t.type === 'expense' ? 'text-destructive' : 'text-success'}>
                {t.amount.toFixed(2)} {t.currency}
              </td>
              <td>{t.type}</td>
              <td>
                {editingId === t.id ? (
                  <select
                    value={editCategoryId}
                    onChange={(e) => setEditCategoryId(e.target.value)}
                    className="rounded border px-1 py-0.5 text-xs"
                  >
                    <option value="">—</option>
                    {categories?.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  t.category_raw
                )}
              </td>
              <td>{t.account}</td>
              <td>
                {editingId === t.id ? (
                  <input
                    value={editComment}
                    onChange={(e) => setEditComment(e.target.value)}
                    className="rounded border px-1 py-0.5 text-xs"
                  />
                ) : (
                  t.comment
                )}
              </td>
              <td>
                {editingId === t.id ? (
                  <input
                    value={editTag}
                    onChange={(e) => setEditTag(e.target.value)}
                    className="rounded border px-1 py-0.5 text-xs"
                  />
                ) : (
                  t.tag
                )}
              </td>
              <td className="space-x-2 py-2 text-right">
                {editingId === t.id ? (
                  <>
                    <Button size="sm" onClick={() => saveEdit(t.id)}>
                      Salva
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setEditingId(null)}>
                      Annulla
                    </Button>
                    {updateMutation.error ? (
                      <p className="mt-1 text-xs text-destructive">{(updateMutation.error as Error).message}</p>
                    ) : null}
                  </>
                ) : (
                  <>
                    <Button size="sm" variant="outline" onClick={() => startEdit(t)}>
                      Modifica
                    </Button>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button size="sm" variant="destructive">
                          Elimina
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogTitle>Eliminare la transazione?</AlertDialogTitle>
                        <AlertDialogDescription>
                          Operazione non reversibile. {t.date.slice(0, 10)} · {t.amount.toFixed(2)} {t.currency} ·{' '}
                          {t.category_raw}
                        </AlertDialogDescription>
                        <div className="mt-4 flex justify-end gap-2">
                          <AlertDialogCancel asChild>
                            <Button variant="outline">Annulla</Button>
                          </AlertDialogCancel>
                          <AlertDialogAction asChild>
                            <Button variant="destructive" onClick={() => deleteMutation.mutate(t.id)}>
                              Elimina
                            </Button>
                          </AlertDialogAction>
                        </div>
                      </AlertDialogContent>
                    </AlertDialog>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {deleteMutation.error ? (
        <p className="mt-3 text-destructive">{(deleteMutation.error as Error).message}</p>
      ) : null}

      <div className="mt-4 flex items-center gap-3 text-sm">
        <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
          Precedente
        </Button>
        <span>
          Pagina {page} · {data?.total} totali
        </span>
        <Button
          size="sm"
          variant="outline"
          disabled={(data?.items.length ?? 0) < (data?.page_size ?? 50)}
          onClick={() => setPage((p) => p + 1)}
        >
          Successiva
        </Button>
      </div>
    </div>
  )
}
