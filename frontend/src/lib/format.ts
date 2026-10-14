// frontend/src/lib/format.ts
//
// Helper di formattazione testuale condivisi dai pannelli dashboard (F13,
// ADR-0030). Nessun colore qui: solo stringhe, il colore resta ai token
// semantici (`text-success`/`text-destructive`/...) o a `chart-config.ts`.

/** Importo in euro con 2 decimali. Stesso stile di `Transactions.tsx`
 * (`{amount.toFixed(2)} {currency}`), ma con `€` letterale invece del
 * campo `currency`: i pannelli dashboard aggregano più conti/transazioni,
 * non mostrano mai una valuta per riga. */
export function formatCurrency(value: number): string {
  return `${value.toFixed(2)} €`
}

/** Wrapper di `formatCurrency` per il prop `formatter` di `<Tooltip>`
 * (Recharts): il tipo dichiarato da Recharts è `ValueType | undefined`
 * (`number | string | ReadonlyArray<...> | undefined`), condiviso con
 * grafici che hanno serie non numeriche — le nostre sono sempre numeriche,
 * ma la firma non lo sa. Parametro `unknown` (non `number`) così resta
 * assegnabile al tipo di Recharts senza restringerlo; guardia a runtime,
 * mai un "NaN €" a schermo se un giorno un valore non numerico arrivasse
 * comunque. */
export function formatCurrencyTooltip(value: unknown): string {
  return formatCurrency(typeof value === 'number' ? value : 0)
}

/** `fraction` è una frazione 0-1 (es. `kpi.savings_rate`/`savings_trend[].savings_rate`
 * del backend, mai una percentuale già moltiplicata) -> stringa tipo `"49.0%"`. */
export function formatPercent(fraction: number): string {
  return `${(fraction * 100).toFixed(1)}%`
}

/** `delta_pct` del backend è GIÀ in punti percentuali, non una frazione
 * (`services/insights.py::month_over_month`: `(current-previous)/previous*100`)
 * — diversa da `formatPercent` sopra, niente doppia moltiplicazione. Può
 * essere `null` (mese precedente a 0 per quella categoria, inclusa una
 * categoria assente): mai un buco silenzioso o un `NaN` visibile, sempre
 * "n/d" esplicito. */
export function formatDeltaPercent(value: number | null): string {
  if (value === null) return 'n/d'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(1)}%`
}

const MONTH_YEAR_FORMATTER = new Intl.DateTimeFormat('it-IT', { month: 'long', year: 'numeric' })

/** `"2026-07"` -> `"Luglio 2026"`. Solo per prosa (titoli/sottotitoli), MAI
 * per i tick degli assi: quelli restano la stringa raw `year_month`, stessa
 * convenzione dei grafici mensili già in `Dashboard.tsx`. Input non
 * conforme a `YYYY-MM` torna invariato invece di lanciare — i chiamanti di
 * questo helper controllano già `!== null` a monte (mai chiamato su un
 * `current_month`/`previous_month` nullo), questo è un secondo livello di
 * difesa, non l'unico. */
export function formatYearMonth(yearMonth: string): string {
  const [year, month] = yearMonth.split('-').map(Number)
  if (!year || !month) return yearMonth
  const label = MONTH_YEAR_FORMATTER.format(new Date(year, month - 1, 1))
  return label.charAt(0).toUpperCase() + label.slice(1)
}
