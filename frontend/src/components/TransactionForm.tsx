// frontend/src/components/TransactionForm.tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { ApiError, api } from '@/lib/api'
import { cn } from '@/lib/utils'

interface Category {
  id: number
  name: string
}

interface Account {
  id: number
  name: string
  display_name: string | null
}

// Sottoinsieme di `_serialize()` (backend/app/routers/transactions.py): solo i
// campi che mostriamo per identificare la gemella nel 409 "duplicate".
interface TwinTransaction {
  date: string
  amount: number
  currency: string
  category_raw: string
  account: string
  comment: string | null
}

// Shape del `detail` per OGNI 409 di POST /transactions (contratto congelato a
// CP1, T7): sempre queste tre chiavi, `transaction` è null per le due reason
// che non hanno una gemella specifica da mostrare.
interface ConflictBody {
  message: string
  reason: 'duplicate' | 'future_date' | 'ordinal_exhausted'
  transaction: TwinTransaction | null
}

interface CreatePayload {
  date: string
  amount: number
  currency: string
  type: string
  category_id: number
  account: string
  comment: string | null
  tag: string | null
  allow_duplicate?: boolean
  confirm_future_date?: boolean
}

interface FormState {
  date: string
  amount: string
  currency: string
  type: string
  category_id: string
  account: string
  comment: string
  tag: string
}

function todayIsoDate(): string {
  // "oggi" nel fuso locale dell'utente, formato YYYY-MM-DD atteso da
  // <input type="date">: senza la correzione dell'offset, .toISOString() da
  // solo darebbe la data UTC, sbagliata di un giorno per chi sta a est di
  // Greenwich la sera tardi (o a ovest la mattina presto).
  const now = new Date()
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 10)
}

function emptyForm(): FormState {
  return {
    date: todayIsoDate(),
    amount: '',
    currency: 'EUR',
    type: 'expense',
    category_id: '',
    account: '',
    comment: '',
    tag: '',
  }
}

export function TransactionForm() {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<FormState>(emptyForm)

  const queryClient = useQueryClient()

  const { data: categories } = useQuery<Category[]>({
    queryKey: ['categories'],
    queryFn: () => api.get<Category[]>('/categories'),
  })
  const { data: accounts } = useQuery<Account[]>({
    queryKey: ['accounts'],
    queryFn: () => api.get<Account[]>('/accounts'),
  })

  const createMutation = useMutation({
    mutationFn: (payload: CreatePayload) => api.post('/transactions', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transactions'] })
      // Oggi nessuna mutation invalida ['insights']: senza, la dashboard
      // resterebbe ferma dopo un inserimento manuale (T10 brief).
      queryClient.invalidateQueries({ queryKey: ['insights'] })
      closeAndReset()
    },
  })

  function closeAndReset() {
    setOpen(false)
    setForm(emptyForm())
    createMutation.reset()
  }

  // Punto unico di aggiornamento campo (review T10, Important #1): un edit dopo un
  // 409 deve far sparire SUBITO banner e pulsante di conferma. Senza questo,
  // "Inserisci comunque"/"Confermi la data?" resterebbero visibili e rimanderebbero
  // ancora createMutation.variables — il payload di PRIMA della correzione, non
  // quello che lo schermo mostra ora. Un solo punto invece di ripeterlo negli 8
  // onChange sotto.
  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }))
    if (createMutation.error) {
      createMutation.reset()
    }
  }

  function buildPayload(): CreatePayload {
    return {
      date: new Date(form.date).toISOString(),
      amount: Number(form.amount),
      currency: form.currency.trim() || 'EUR',
      type: form.type,
      category_id: Number(form.category_id),
      account: form.account.trim(),
      comment: form.comment.trim() || null,
      tag: form.tag.trim() || null,
    }
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (createMutation.isPending) return
    createMutation.mutate(buildPayload())
  }

  // Ripropongono l'ULTIMO payload effettivamente inviato (via createMutation.variables),
  // non i campi correnti del form — l'utente ha visto l'avviso su QUEI dati e ha
  // scelto di procedere, non su un'eventuale modifica successiva non ancora inviata.
  function resubmitAsDuplicate() {
    const previous = createMutation.variables
    if (!previous || createMutation.isPending) return
    createMutation.mutate({ ...previous, allow_duplicate: true })
  }

  function resubmitWithFutureDateConfirmed() {
    const previous = createMutation.variables
    if (!previous || createMutation.isPending) return
    createMutation.mutate({ ...previous, confirm_future_date: true })
  }

  // instanceof, non un cast cieco: se api.ts tornasse a un `throw new Error(...)`
  // nativo, questo controllo torna false e i pulsanti di conferma sotto spariscono
  // — la dipendenza da T8 (ApiError con .status/.body) è rumorosa, non silenziosa.
  const mutationError = createMutation.error
  const apiError = mutationError instanceof ApiError ? mutationError : null
  const conflict: ConflictBody | null =
    apiError && apiError.status === 409 ? (apiError.body as ConflictBody) : null

  const isFormValid =
    form.date !== '' &&
    Number(form.amount) > 0 &&
    form.category_id !== '' &&
    form.account.trim() !== ''

  if (!open) {
    return (
      <Button size="sm" onClick={() => setOpen(true)}>
        Nuova transazione
      </Button>
    )
  }

  return (
    // Solo React state (`open`): nessun history.pushState / location.hash qui o
    // altrove nel componente — il back del browser non deve chiudere il dialog,
    // deve fare quello che avrebbe fatto comunque (criterio T10).
    <div
      className="fixed inset-0 z-50 bg-black/50"
      // SOLO setOpen(false), MAI closeAndReset qui (review T10, Important #2): un
      // click sul backdrop può scattare anche da un drag di selezione testo iniziato
      // dentro un campo (es. Commento) e rilasciato fuori dal pannello — il click
      // sintetico punta all'antenato comune di mousedown/mouseup, cioè il backdrop
      // stesso, e lo stopPropagation sul pannello sotto non lo previene (non è un
      // bubbling dal pannello, il target è già il backdrop). Azzerare form/mutation
      // qui perderebbe input dell'utente senza conferma su un gesto incidentale;
      // riaprendo il form i dati sono ancora lì. Solo Annulla o un salvataggio
      // riuscito azzerano davvero (closeAndReset).
      onClick={() => setOpen(false)}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Nuova transazione"
        className="fixed left-1/2 top-1/2 max-h-[90vh] w-full max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg bg-background p-6 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-4 text-lg font-semibold">Nuova transazione</h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <Label htmlFor="txn-date">Data</Label>
            <Input
              id="txn-date"
              type="date"
              required
              value={form.date}
              onChange={(e) => updateField('date', e.target.value)}
            />
          </div>

          <div className="flex gap-3">
            <div className="flex-1">
              <Label htmlFor="txn-amount">Importo</Label>
              <Input
                id="txn-amount"
                type="number"
                step="0.01"
                min="0.01"
                required
                value={form.amount}
                onChange={(e) => updateField('amount', e.target.value)}
              />
            </div>
            <div className="w-24">
              <Label htmlFor="txn-currency">Valuta</Label>
              <Input
                id="txn-currency"
                value={form.currency}
                onChange={(e) => updateField('currency', e.target.value)}
              />
            </div>
          </div>

          <div className="flex gap-3">
            <div className="flex-1">
              <Label htmlFor="txn-type">Tipo</Label>
              <Select
                id="txn-type"
                value={form.type}
                onChange={(e) => updateField('type', e.target.value)}
              >
                <option value="expense">Uscita</option>
                <option value="income">Entrata</option>
              </Select>
            </div>
            <div className="flex-1">
              <Label htmlFor="txn-category">Categoria</Label>
              <Select
                id="txn-category"
                required
                value={form.category_id}
                onChange={(e) => updateField('category_id', e.target.value)}
              >
                <option value="" disabled>
                  Seleziona...
                </option>
                {categories?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div>
            <Label htmlFor="txn-account">Conto</Label>
            <Input
              id="txn-account"
              list="txn-account-options"
              required
              value={form.account}
              onChange={(e) => updateField('account', e.target.value)}
            />
            {/* Suggerisce i conti esistenti ma non li impone: il backend registra
                as-is anche un conto mai visto prima (ADR-0006), quindi un input
                libero — non una <Select> chiusa alle sole opzioni note — è l'unica
                scelta che non blocca il caso d'uso reale (conto nuovo di zecca). */}
            <datalist id="txn-account-options">
              {accounts?.map((a) => (
                <option key={a.id} value={a.name} />
              ))}
            </datalist>
          </div>

          <div>
            <Label htmlFor="txn-comment">Commento</Label>
            <Input
              id="txn-comment"
              value={form.comment}
              onChange={(e) => updateField('comment', e.target.value)}
            />
          </div>

          <div>
            <Label htmlFor="txn-tag">Tag</Label>
            <Input
              id="txn-tag"
              value={form.tag}
              onChange={(e) => updateField('tag', e.target.value)}
            />
          </div>

          {conflict ? (
            <div
              className={cn(
                'rounded border px-3 py-2 text-sm',
                conflict.reason === 'ordinal_exhausted'
                  ? 'border-destructive bg-destructive/10 text-destructive'
                  : 'border-warning bg-warning/10 text-warning-foreground',
              )}
            >
              <p>{conflict.message}</p>
              {conflict.reason === 'duplicate' && conflict.transaction ? (
                <p className="mt-1 text-xs opacity-90">
                  {conflict.transaction.date.slice(0, 10)} · {conflict.transaction.amount.toFixed(2)}{' '}
                  {conflict.transaction.currency} · {conflict.transaction.category_raw} ·{' '}
                  {conflict.transaction.account}
                  {conflict.transaction.comment ? ` · ${conflict.transaction.comment}` : ''}
                </p>
              ) : null}
              {conflict.reason === 'duplicate' ? (
                <Button
                  type="button"
                  size="sm"
                  className="mt-2"
                  disabled={createMutation.isPending}
                  onClick={resubmitAsDuplicate}
                >
                  Inserisci comunque
                </Button>
              ) : null}
              {conflict.reason === 'future_date' ? (
                <Button
                  type="button"
                  size="sm"
                  className="mt-2"
                  disabled={createMutation.isPending}
                  onClick={resubmitWithFutureDateConfirmed}
                >
                  Confermi la data?
                </Button>
              ) : null}
            </div>
          ) : mutationError ? (
            <p className="text-sm text-destructive">{mutationError.message}</p>
          ) : null}

          <div className="mt-4 flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={closeAndReset}>
              Annulla
            </Button>
            <Button type="submit" disabled={!isFormValid || createMutation.isPending}>
              {createMutation.isPending ? 'Salvataggio...' : 'Salva'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
