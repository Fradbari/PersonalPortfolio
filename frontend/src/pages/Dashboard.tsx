import { useQuery } from '@tanstack/react-query'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '@/lib/api'

interface Insights {
  monthly_trend: { year_month: string; income: number; expense: number }[]
  category_breakdown: { category_raw: string; total: number }[]
  cumulative_balance: { year_month: string; balance: number; cumulative_balance: number }[]
  balance_by_account: { account: string; balance: number }[]
}

export function Dashboard() {
  const { data, isLoading, error } = useQuery<Insights>({
    queryKey: ['insights'],
    queryFn: () => api.get<Insights>('/insights'),
  })

  if (isLoading) return <p>Caricamento...</p>
  if (error) return <p className="text-red-600">Errore: {(error as Error).message}</p>
  if (!data) return null

  return (
    <div className="grid grid-cols-2 gap-6">
      <div className="rounded-lg border bg-white p-4">
        <h2 className="mb-4 font-semibold">Entrate vs uscite (mensile)</h2>
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={data.monthly_trend}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="year_month" />
            <YAxis />
            <Tooltip />
            <Line type="monotone" dataKey="income" stroke="#16a34a" name="Entrate" />
            <Line type="monotone" dataKey="expense" stroke="#dc2626" name="Uscite" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="rounded-lg border bg-white p-4">
        <h2 className="mb-4 font-semibold">Spesa per categoria</h2>
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={data.category_breakdown}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="category_raw" hide />
            <YAxis />
            <Tooltip />
            <Bar dataKey="total" fill="#2563eb" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="rounded-lg border bg-white p-4">
        <h2 className="mb-4 font-semibold">Saldo cumulato</h2>
        <ResponsiveContainer width="100%" height={250}>
          <AreaChart data={data.cumulative_balance}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="year_month" />
            <YAxis />
            <Tooltip />
            <Area type="monotone" dataKey="cumulative_balance" stroke="#7c3aed" fill="#ddd6fe" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="rounded-lg border bg-white p-4">
        <h2 className="mb-4 font-semibold">Saldo per conto</h2>
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={data.balance_by_account} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" />
            <YAxis dataKey="account" type="category" width={100} />
            <Tooltip />
            <Bar dataKey="balance" fill="#0891b2" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
