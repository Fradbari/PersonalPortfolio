// frontend/src/components/dashboard/CategoryDonutPanel.tsx
//
// Spesa per categoria (ADR-0030 p.5/p.6): DONUT, non treemap. La soglia
// "treemap solo oltre ~15 categorie" è una nota di design, non una
// condizione da implementare (ADR-0030 p.6): nessun `if` che scelga il tipo
// di grafico a runtime. Il backend aggrega già a <=7 elementi (top 6 +
// "Altro"), che mappano 1:1 sui 7 slot di `chartColors` (T12).
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { chartColors, chartTooltip } from '@/lib/chart-config'
import { formatCurrencyTooltip } from '@/lib/format'
import { DashboardPanel } from './DashboardPanel'
import { EmptyState } from './EmptyState'

interface CategoryDonutSlice {
  category_raw: string
  total: number
}

export function CategoryDonutPanel({ data }: { data: CategoryDonutSlice[] }) {
  return (
    <DashboardPanel title="Spesa per categoria" subtitle="Top 6 categorie + Altro · ultimi 12 mesi">
      {data.length === 0 ? (
        <EmptyState />
      ) : (
        <ResponsiveContainer width="100%" height={250}>
          <PieChart>
            <Pie
              data={data}
              dataKey="total"
              nameKey="category_raw"
              innerRadius="55%"
              outerRadius="80%"
              paddingAngle={2}
            >
              {data.map((entry, index) => (
                <Cell key={entry.category_raw} fill={chartColors[index % chartColors.length]} />
              ))}
            </Pie>
            <Tooltip contentStyle={chartTooltip} formatter={formatCurrencyTooltip} />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      )}
    </DashboardPanel>
  )
}
