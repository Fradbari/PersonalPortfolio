// frontend/src/components/dashboard/KpiCards.tsx
//
// Riga di 4 KPI (ADR-0030 p.5): entrate, uscite, netto, tasso di risparmio,
// sulla stessa finestra risolta (`months`) degli altri pannelli finestrati.
// Card semplici, non `DashboardPanel`: qui non c'è alcun grafico, il layout
// label+numero è diverso dagli altri sei pannelli.
import { formatCurrency, formatPercent } from '@/lib/format'

interface Kpi {
  income: number
  expense: number
  net: number
  savings_rate: number
}

// Segno del valore stesso (non della spesa): per `net`/`savings_rate` un
// valore negativo è un peggioramento (si è speso più di quanto entrato).
function toneForSign(value: number): string {
  if (value > 0) return 'text-success'
  if (value < 0) return 'text-destructive'
  return 'text-foreground'
}

const CARDS: {
  key: keyof Kpi
  label: string
  format: (value: number) => string
  tone: (value: number) => string
}[] = [
  { key: 'income', label: 'Entrate', format: formatCurrency, tone: () => 'text-success' },
  { key: 'expense', label: 'Uscite', format: formatCurrency, tone: () => 'text-destructive' },
  { key: 'net', label: 'Netto', format: formatCurrency, tone: toneForSign },
  { key: 'savings_rate', label: 'Tasso di risparmio', format: formatPercent, tone: toneForSign },
]

export function KpiCards({ kpi }: { kpi: Kpi }) {
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      {CARDS.map((card) => (
        <div key={card.key} className="rounded-lg border bg-card p-4">
          <p className="text-xs text-muted-foreground">{card.label}</p>
          <p className={`mt-1 text-2xl font-semibold ${card.tone(kpi[card.key])}`}>{card.format(kpi[card.key])}</p>
        </div>
      ))}
    </div>
  )
}
