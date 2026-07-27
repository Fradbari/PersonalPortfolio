// frontend/src/components/dashboard/CashFlowPanel.tsx
//
// Cash flow mensile (ADR-0030 p.5): barre entrate/uscite + linea netto sulla
// stessa finestra scorrevole di `months` (default 12). Array di lunghezza
// variabile — `months` tronca, non riempie (spec F13 §7): nessun mese a
// zero inventato per pareggiare la finestra, coerente con `monthly_trend`
// che aggrega via `GROUP BY` senza emettere mesi vuoti.
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { chartAxis, chartColors, chartGrid, chartTooltip } from '@/lib/chart-config'
import { formatCurrencyTooltip } from '@/lib/format'
import { DashboardPanel } from './DashboardPanel'
import { EmptyState } from './EmptyState'

interface CashFlowPoint {
  year_month: string
  income: number
  expense: number
  net: number
}

export function CashFlowPanel({ data }: { data: CashFlowPoint[] }) {
  return (
    <DashboardPanel title="Cash flow mensile" subtitle="Entrate, uscite e netto · ultimi 12 mesi">
      {data.length === 0 ? (
        <EmptyState />
      ) : (
        <ResponsiveContainer width="100%" height={250}>
          <ComposedChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke={chartGrid} />
            <XAxis dataKey="year_month" stroke={chartAxis} tick={{ fill: chartAxis }} />
            <YAxis stroke={chartAxis} tick={{ fill: chartAxis }} />
            <Tooltip contentStyle={chartTooltip} formatter={formatCurrencyTooltip} />
            <Legend />
            <Bar dataKey="income" name="Entrate" fill={chartColors[1]} />
            <Bar dataKey="expense" name="Uscite" fill={chartColors[0]} />
            <Line type="monotone" dataKey="net" name="Netto" stroke={chartColors[3]} strokeWidth={2} dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </DashboardPanel>
  )
}
