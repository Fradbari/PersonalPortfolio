// frontend/src/components/dashboard/CumulativeBalancePanel.tsx
//
// Saldo cumulato (ADR-0030 p.4/p.5): somma di entrate meno uscite mese su
// mese, sulla finestra risolta di `months` (default 12) — NON tutto lo
// storico come la vecchia versione da `GET /insights` che questo pannello
// sostituisce (T14). MAI "patrimonio": non esiste alcun modello
// asset/passività, solo un cumulato di transazioni (ADR-0030 p.4).
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { chartAxis, chartColors, chartGrid, chartTooltip } from '@/lib/chart-config'
import { formatCurrencyTooltip } from '@/lib/format'
import { DashboardPanel } from './DashboardPanel'
import { EmptyState } from './EmptyState'

interface CumulativeBalancePoint {
  year_month: string
  balance: number
  cumulative_balance: number
}

export function CumulativeBalancePanel({ data }: { data: CumulativeBalancePoint[] }) {
  return (
    <DashboardPanel title="Saldo cumulato" subtitle="Entrate meno uscite, cumulate · ultimi 12 mesi">
      {data.length === 0 ? (
        <EmptyState />
      ) : (
        <ResponsiveContainer width="100%" height={250}>
          <AreaChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke={chartGrid} />
            <XAxis dataKey="year_month" stroke={chartAxis} tick={{ fill: chartAxis }} />
            <YAxis stroke={chartAxis} tick={{ fill: chartAxis }} />
            <Tooltip contentStyle={chartTooltip} formatter={formatCurrencyTooltip} />
            <Area
              type="monotone"
              dataKey="cumulative_balance"
              name="Saldo cumulato"
              stroke={chartColors[3]}
              fill={chartColors[3]}
              fillOpacity={0.2}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </DashboardPanel>
  )
}
