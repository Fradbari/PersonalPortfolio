// frontend/src/components/dashboard/MonthOverMonthPanel.tsx
//
// Confronto mese su mese (ADR-0030 p.5), per categoria di spesa (solo
// uscite, ratificato a CP1b): ancorato all'ultimo mese con dati reali, non
// a "oggi" (`services/insights.py::month_over_month`) — quindi NON riceve
// la finestra `months` degli altri cinque pannelli.
//
// A DB vuoto `current_month`/`previous_month` sono `null` (mai una stringa
// vuota, mai assenti): il guard sotto è l'UNICO punto di controllo, fatto
// una volta sola prima di formattare qualunque mese — da qui in poi
// `currentMonth`/`previousMonth` sono garantiti stringhe, niente
// `.split()`/formattazione su un valore nullo più giù nel componente.
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { chartAxis, chartColors, chartGrid, chartTooltip } from '@/lib/chart-config'
import { formatCurrencyTooltip, formatDeltaPercent, formatYearMonth } from '@/lib/format'
import { DashboardPanel } from './DashboardPanel'
import { EmptyState } from './EmptyState'

interface MonthOverMonth {
  current_month: string | null
  previous_month: string | null
  current: Record<string, number>
  previous: Record<string, number>
  delta_pct: Record<string, number | null>
}

interface Row {
  category: string
  current: number
  previous: number
  delta: number | null
}

// Categorie di SOLA spesa (month_over_month è solo-uscite): un delta
// positivo vuol dire "si è speso di più", un peggioramento — quindi
// destructive, non success. Segno invertito rispetto a `KpiCards`/`net`,
// dove positivo è sempre un bene: lì il valore è un saldo, qui è una spesa.
function deltaTone(delta: number | null): string {
  if (delta === null) return 'text-muted-foreground'
  if (delta > 0) return 'text-destructive'
  if (delta < 0) return 'text-success'
  return 'text-muted-foreground'
}

export function MonthOverMonthPanel({ data }: { data: MonthOverMonth }) {
  const { current_month: currentMonth, previous_month: previousMonth, current, previous, delta_pct: deltaPct } = data

  if (!currentMonth || !previousMonth) {
    return (
      <DashboardPanel title="Confronto mese su mese">
        <EmptyState />
      </DashboardPanel>
    )
  }

  // Unione delle categorie di entrambi i mesi (il contratto backend garantisce
  // già le stesse chiavi in `current`/`previous`/`delta_pct`, ma l'unione resta
  // corretta anche se un giorno smettesse di valere — `?? 0`/`?? null` sotto
  // gestiscono comunque una chiave mancante da un lato).
  const categories = Array.from(new Set([...Object.keys(current), ...Object.keys(previous)]))
  const rows: Row[] = categories.map((category) => ({
    category,
    current: current[category] ?? 0,
    previous: previous[category] ?? 0,
    delta: deltaPct[category] ?? null,
  }))

  const currentLabel = formatYearMonth(currentMonth)
  const previousLabel = formatYearMonth(previousMonth)

  return (
    <DashboardPanel
      title="Confronto mese su mese"
      subtitle={`${currentLabel} vs ${previousLabel} · spese per categoria`}
    >
      {rows.length === 0 ? (
        <EmptyState />
      ) : (
        <>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" stroke={chartGrid} />
              <XAxis dataKey="category" hide stroke={chartAxis} tick={{ fill: chartAxis }} />
              <YAxis stroke={chartAxis} tick={{ fill: chartAxis }} />
              <Tooltip contentStyle={chartTooltip} formatter={formatCurrencyTooltip} />
              <Legend />
              <Bar dataKey="previous" name={previousLabel} fill={chartColors[6]} />
              <Bar dataKey="current" name={currentLabel} fill={chartColors[2]} />
            </BarChart>
          </ResponsiveContainer>
          {/* Delta % esplicito per categoria: il grafico da solo non rende leggibile
              un "n/d" (mese precedente a 0), questa lista sì. */}
          <ul className="mt-3 max-h-24 space-y-1 overflow-y-auto text-xs">
            {rows.map((row) => (
              <li key={row.category} className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">{row.category}</span>
                <span className={deltaTone(row.delta)}>{formatDeltaPercent(row.delta)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </DashboardPanel>
  )
}
