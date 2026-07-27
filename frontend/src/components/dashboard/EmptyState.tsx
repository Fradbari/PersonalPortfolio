// frontend/src/components/dashboard/EmptyState.tsx
//
// Placeholder per un pannello senza dati (DB vuoto, o finestra `months`
// senza transazioni). Il contratto di `/insights/panels` garantisce liste
// vuote — mai `null` — quindi questo è lo stato normale a DB vuoto, non un
// errore (spec F13 §7): niente banner rosso, solo un testo neutro.
export function EmptyState() {
  return (
    <div className="flex h-[250px] items-center justify-center text-sm text-muted-foreground">
      Nessun dato disponibile.
    </div>
  )
}
