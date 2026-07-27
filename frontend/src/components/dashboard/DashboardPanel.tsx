// frontend/src/components/dashboard/DashboardPanel.tsx
//
// Wrapper di presentazione condiviso dai pannelli dashboard (F13): stessa
// card (`rounded-lg border bg-card p-4`) e schema titolo/sottotitolo già in
// uso altrove nell'app (es. `Settings.tsx`, `<section>`). Non è un
// "framework pannelli": solo il markup che si ripete identico in ogni
// pannello, senza logica di dati.
import type { ReactNode } from 'react'

interface DashboardPanelProps {
  title: string
  subtitle?: string
  children: ReactNode
}

export function DashboardPanel({ title, subtitle, children }: DashboardPanelProps) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="mb-4">
        <h2 className="font-semibold">{title}</h2>
        {subtitle ? <p className="text-xs text-muted-foreground">{subtitle}</p> : null}
      </div>
      {children}
    </div>
  )
}
