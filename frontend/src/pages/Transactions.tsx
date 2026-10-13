import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { TransactionForm } from '@/components/TransactionForm'
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

interface Account {
  id: number
  name: string
  display_name: string | null
}

// Nomi letterali dei filtri accettati da `GET /transactions` (ADR-0029 p.5), esclusa
// `page` che ha una gestione propria (`setPage`, sotto). Questa e' l'UNICA lista che
// pilota lettura da `useSearchParams`, costruzione della query string di fetch E la
// `queryKey` di TanStack Query (`filters` sotto e' costruito da qui e passato a
// entrambe) — un filtro nuovo si aggiunge SOLO qui: non puo' finire nella fetch senza
// finire anche nella queryKey, perche' provengono dallo stesso oggetto (T11 brief:
// dimenticare l'aggiunta alla queryKey e' l'errore che fallisce in silenzio).
const FILTER_KEYS = [
  'year_month',
  'date_from',
  'date_to',
  'category_id',
  'account',
  'type',
  'amount_min',
  'amount_max',
  'tag',
  'q',
] as const

type FilterKey = (typeof FILTER_KEYS)[number]
type Filters = Record<FilterKey, string>

export function Transactions() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editComment, setEditComment] = useState('')
  const [editTag, setEditTag] = useState('')
  const [editCategoryId, setEditCategoryId] = useState('')

  const queryClient = useQueryClient()

  // Stato dei filtri: SOLO l'URL (ADR-0029 p.7). Nessun useState parallelo — due fonti
  // di verita' divergerebbero al primo "indietro" del browser.
  const filters = Object.fromEntries(
    FILTER_KEYS.map((key): [FilterKey, string] => [key, searchParams.get(key) ?? '']),
  ) as Filters
  const page = Number(searchParams.get('page')) || 1

  // Punto unico di scrittura per ogni filtro: azzera sempre la pagina, perche' una
  // condizione di filtro nuova invalida la posizione di scorrimento corrente.
  // `replace: true`: senza, ogni carattere digitato in "Cerca"/"Tag" spingerebbe una
  // nuova voce di history — "indietro" dopo aver scritto una parola di 6 lettere
  // richiederebbe 6 click per uscire dalla ricerca invece di uno. La navigazione reale
  // (cambio pagina, sotto) resta push, cosi' "indietro" torna alla pagina precedente
  // dei risultati, non fuori dai filtri.
  function setFilter(key: FilterKey, value: string) {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (value) {
          next.set(key, value)
        } else {
          next.delete(key)
        }
        next.set('page', '1')
        return next
      },
      { replace: true },
    )
  }

  function setPage(nextPage: number) {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('page', String(nextPage))
      return next
    })
  }

  function resetFilters() {
    setSearchParams({}, { replace: true })
  }

  const params = new URLSearchParams()
  FILTER_KEYS.forEach((key) => {
    if (filters[key]) params.set(key, filters[key])
  })
  params.set('page', String(page))

  const {
    data,
    isLoading,
    isError: isTransactionsError,
    error: transactionsError,
  } = useQuery<TransactionsResponse>({
    // `filters` e `params` sopra vengono dallo stesso `FILTER_KEYS`: un filtro
    // aggiunto all'uno e' per costruzione gia' nell'altro (vedi commento su
    // FILTER_KEYS). `page` resta un elemento separato della chiave, come nello
    // stato precedente a questo task.
    queryKey: ['transactions', filters, page],
    queryFn: () => api.get<TransactionsResponse>(`/transactions?${params.toString()}`),
    // Senza questo, ogni nuova combinazione di filtri (incluso un singolo carattere
    // digitato in "Cerca"/"Tag") fa sparire momentaneamente `data`, che a sua volta fa
    // scattare il ramo `isLoading` sotto: l'intera pagina — barra filtri compresa —
    // smonterebbe e rimonterebbe a ogni tasto premuto, perdendo il focus dell'input di
    // ricerca. `keepPreviousData` mantiene l'ultima risposta valida a schermo finché la
    // nuova non arriva, esattamente il pattern raccomandato da TanStack Query per liste
    // filtrate/paginate.
    placeholderData: keepPreviousData,
  })

  const { data: categories } = useQuery<Category[]>({
    queryKey: ['categories'],
    queryFn: () => api.get<Category[]>('/categories'),
  })

  const { data: accounts } = useQuery<Account[]>({
    queryKey: ['accounts'],
    queryFn: () => api.get<Account[]>('/accounts'),
  })

  const updateMutation = useMutation({
    mutationFn: (vars: { id: number; body: Record<string, unknown> }) =>
      api.put(`/transactions/${vars.id}`, vars.body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transactions'] })
      queryClient.invalidateQueries({ queryKey: ['insights'] })
      setEditingId(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/transactions/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transactions'] })
      queryClient.invalidateQueries({ queryKey: ['insights'] })
    },
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
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Transazioni</h2>
        <TransactionForm />
      </div>

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Mese
          <input
            type="month"
            value={filters.year_month}
            onChange={(e) => setFilter('year_month', e.target.value)}
            className="rounded border px-2 py-1 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Dal
          <input
            type="date"
            value={filters.date_from}
            onChange={(e) => setFilter('date_from', e.target.value)}
            className="rounded border px-2 py-1 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Al
          <input
            type="date"
            value={filters.date_to}
            onChange={(e) => setFilter('date_to', e.target.value)}
            className="rounded border px-2 py-1 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Tipo
          <select
            value={filters.type}
            onChange={(e) => setFilter('type', e.target.value)}
            className="rounded border px-2 py-1 text-sm"
          >
            <option value="">Tutti i tipi</option>
            <option value="expense">Uscite</option>
            <option value="income">Entrate</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Categoria
          <select
            value={filters.category_id}
            onChange={(e) => setFilter('category_id', e.target.value)}
            className="rounded border px-2 py-1 text-sm"
          >
            <option value="">Tutte le categorie</option>
            {categories?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Conto
          <select
            value={filters.account}
            onChange={(e) => setFilter('account', e.target.value)}
            className="rounded border px-2 py-1 text-sm"
          >
            <option value="">Tutti i conti</option>
            {accounts?.map((a) => (
              <option key={a.id} value={a.name}>
                {a.display_name ?? a.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Importo min
          <input
            type="number"
            step="0.01"
            min="0"
            value={filters.amount_min}
            onChange={(e) => setFilter('amount_min', e.target.value)}
            className="w-24 rounded border px-2 py-1 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Importo max
          <input
            type="number"
            step="0.01"
            min="0"
            value={filters.amount_max}
            onChange={(e) => setFilter('amount_max', e.target.value)}
            className="w-24 rounded border px-2 py-1 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Tag
          <input
            type="text"
            value={filters.tag}
            onChange={(e) => setFilter('tag', e.target.value)}
            className="rounded border px-2 py-1 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Cerca (commento, tag, categoria grezza, conto)
          <input
            type="text"
            value={filters.q}
            onChange={(e) => setFilter('q', e.target.value)}
            className="w-56 rounded border px-2 py-1 text-sm"
          />
        </label>
        <Button size="sm" variant="outline" onClick={resetFilters}>
          Cancella filtri
        </Button>
      </div>

      {isTransactionsError ? (
        // Il backend risponde 503 (non 500, non un 200 vuoto) quando l'indice FTS5
        // manca (search.py) proprio per distinguere "indice giu'" da "zero risultati" —
        // con `keepPreviousData` un errore scarta il placeholder e `data` torna
        // undefined, quindi senza questo la tabella si limiterebbe a apparire vuota,
        // indistinguibile da una ricerca senza esiti. Stesso pattern di
        // `deleteMutation.error` sotto: `(error as Error).message`, `ApiError` estende
        // `Error` e il body del 503 e' una stringa semplice.
        <p className="mb-3 text-destructive">{(transactionsError as Error).message}</p>
      ) : null}

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
        <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>
          Precedente
        </Button>
        <span>
          Pagina {page} · {data?.total} totali
        </span>
        <Button
          size="sm"
          variant="outline"
          disabled={(data?.items.length ?? 0) < (data?.page_size ?? 50)}
          onClick={() => setPage(page + 1)}
        >
          Successiva
        </Button>
      </div>
    </div>
  )
}
