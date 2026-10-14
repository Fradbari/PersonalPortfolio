// frontend/src/components/dashboard/SavingsTrendPanel.tsx
//
// Trend risparmio (ADR-0030 p.5): (entrate - uscite) / entrate, mese su
// mese, sulla stessa finestra di `cash_flow`/`cumulative_balance`. Il
// backend restituisce una frazione 0-1 (mai null/NaN, `0.0` quando
// `income == 0` — `services/insights.py::savings_rate_fraction`); qui si
// converte in punti percentuali SOLO per la visualizzazione, un'unica
// volta, senza toccare il dato originale.
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { chartAxis, chartColors, chartGrid, chartTooltip } from '@/lib/chart-config'
import { DashboardPanel } from './DashboardPanel'
import { EmptyState } from './EmptyState'

interface SavingsTrendPoint {
  year_month: string
  savings_rate: number
}

interface ChartPoint {
  year_month: string
  savings_rate_pct: number
}

export function SavingsTrendPanel({ data }: { data: SavingsTrendPoint[] }) {
  const chartData: ChartPoint[] = data.map((point) => ({
    year_month: point.year_month,
    savings_rate_pct: Math.round(point.savings_rate * 1000) / 10,
  }))

  return (
    <DashboardPanel title="Trend risparmio" subtitle="(entrate - uscite) / entrate · ultimi 12 mesi">
      {chartData.length === 0 ? (
        <EmptyState />
      ) : (
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke={chartGrid} />
            <XAxis dataKey="year_month" stroke={chartAxis} tick={{ fill: chartAxis }} />
            <YAxis stroke={chartAxis} tick={{ fill: chartAxis }} tickFormatter={(value: number) => `${value}%`} />
            <Tooltip contentStyle={chartTooltip} />
            <Line
              type="monotone"
              dataKey="savings_rate_pct"
              name="Tasso di risparmio"
              unit="%"
              stroke={chartColors[5]}
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </DashboardPanel>
  )
}
