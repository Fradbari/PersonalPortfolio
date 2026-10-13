// frontend/src/pages/Dashboard.tsx
//
// F13 (ADR-0030): sei pannelli complementari a Metabase (che resta
// invariata, ADR-0004/ADR-0019 non superati) su `GET /insights/panels` —
// saldo cumulato, cash flow mensile, spesa per categoria (donut), trend
// risparmio, confronto mese su mese, riga di 4 KPI — più "Saldo per conto",
// mantenuto da `GET /insights` (nessun equivalente nel nuovo contratto,
// nessuno ha chiesto di rimuoverlo).
//
// Tre pannelli precedenti di questa pagina (entrate/uscite mensili, spesa
// per categoria, saldo cumulato ALL-TIME) sono SOSTITUITI dalle versioni
// nuove sopra, non affiancati: mostrare vecchio e nuovo "Saldo cumulato"
// fianco a fianco con numeri diversi (all-time vs finestrato a `months`)
// sotto lo stesso nome avrebbe confuso più che aiutato. Decisione presa in
// dispatch T14, da confermare a CP2 (checkpoint umano, giudizio visivo).
import { useQuery } from '@tanstack/react-query'
import { BalanceByAccountPanel } from '@/components/dashboard/BalanceByAccountPanel'
import { CashFlowPanel } from '@/components/dashboard/CashFlowPanel'
import { CategoryDonutPanel } from '@/components/dashboard/CategoryDonutPanel'
import { CumulativeBalancePanel } from '@/components/dashboard/CumulativeBalancePanel'
import { KpiCards } from '@/components/dashboard/KpiCards'
import { MonthOverMonthPanel } from '@/components/dashboard/MonthOverMonthPanel'
import { SavingsTrendPanel } from '@/components/dashboard/SavingsTrendPanel'
import { api } from '@/lib/api'

// Contratto congelato a CP1b (spec F13 §7, verificato dal vivo in T13):
// forma a chiavi nominate, non `{panels: [...]}`. Gli array sono di
// lunghezza variabile — `months` tronca, non riempie — e possono essere
// vuoti (mai `null`) a DB vuoto o su una finestra senza transazioni.
interface InsightsPanels {
  kpi: { income: number; expense: number; net: number; savings_rate: number }
  cumulative_balance: { year_month: string; balance: number; cumulative_balance: number }[]
  cash_flow: { year_month: string; income: number; expense: number; net: number }[]
  category_donut: { category_raw: string; total: number }[]
  savings_trend: { year_month: string; savings_rate: number }[]
  month_over_month: {
    current_month: string | null
    previous_month: string | null
    current: Record<string, number>
    previous: Record<string, number>
    delta_pct: Record<string, number | null>
  }
}

// Sottoinsieme di `GET /insights` (F5/F6): qui serve solo `balance_by_account`,
// l'unico pannello di questa pagina rimasto su questo endpoint (T14) — gli
// altri tre campi (`monthly_trend`/`category_breakdown`/`cumulative_balance`)
// sono quelli sostituiti dai pannelli nuovi sopra, non dichiarati qui perché
// non consumati.
interface Insights {
  balance_by_account: { account: string; balance: number }[]
}

export function Dashboard() {
  const {
    data: panels,
    isLoading: panelsLoading,
    error: panelsError,
  } = useQuery<InsightsPanels>({
    queryKey: ['insights', 'panels'],
    queryFn: () => api.get<InsightsPanels>('/insights/panels'),
  })

  const {
    data: insights,
    isLoading: insightsLoading,
    error: insightsError,
  } = useQuery<Insights>({
    queryKey: ['insights'],
    queryFn: () => api.get<Insights>('/insights'),
  })

  if (panelsLoading || insightsLoading) return <p>Caricamento...</p>
  if (panelsError) return <p className="text-destructive">Errore: {(panelsError as Error).message}</p>
  if (insightsError) return <p className="text-destructive">Errore: {(insightsError as Error).message}</p>
  if (!panels || !insights) return null

  return (
    <div className="space-y-6">
      <KpiCards kpi={panels.kpi} />
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <CumulativeBalancePanel data={panels.cumulative_balance} />
        <CashFlowPanel data={panels.cash_flow} />
        <CategoryDonutPanel data={panels.category_donut} />
        <SavingsTrendPanel data={panels.savings_trend} />
        <MonthOverMonthPanel data={panels.month_over_month} />
        <BalanceByAccountPanel data={insights.balance_by_account} />
      </div>
    </div>
  )
}
