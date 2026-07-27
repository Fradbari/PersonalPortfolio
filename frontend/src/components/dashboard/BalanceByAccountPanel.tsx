// frontend/src/components/dashboard/BalanceByAccountPanel.tsx
//
// Saldo per conto: MANTENUTO da `GET /insights` (non ha equivalente nel
// contratto di `/insights/panels` — nessuno ha chiesto di rimuoverlo, T14).
// Stessa query di prima (`balance_by_account`, tutto lo storico, nessuna
// finestra `months`: non è uno dei sei pannelli nuovi).
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { chartAxis, chartColors, chartGrid, chartTooltip } from '@/lib/chart-config'
import { formatCurrencyTooltip } from '@/lib/format'
import { DashboardPanel } from './DashboardPanel'
import { EmptyState } from './EmptyState'

interface BalanceByAccountPoint {
  account: string
  balance: number
}

export function BalanceByAccountPanel({ data }: { data: BalanceByAccountPoint[] }) {
  return (
    <DashboardPanel title="Saldo per conto">
      {data.length === 0 ? (
        <EmptyState />
      ) : (
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={data} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" stroke={chartGrid} />
            <XAxis type="number" stroke={chartAxis} tick={{ fill: chartAxis }} />
            <YAxis dataKey="account" type="category" width={100} stroke={chartAxis} tick={{ fill: chartAxis }} />
            <Tooltip contentStyle={chartTooltip} formatter={formatCurrencyTooltip} />
            <Bar dataKey="balance" fill={chartColors[4]} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </DashboardPanel>
  )
}
