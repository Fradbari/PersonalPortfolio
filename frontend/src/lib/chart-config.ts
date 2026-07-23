/**
 * Configurazione colori condivisa per i grafici Recharts (ADR-0026).
 *
 * Tutti i valori sono stringhe CSS `hsl(var(--token))` risolte dal browser a
 * runtime: nessun `getComputedStyle`, nessuna lettura una tantum al mount.
 * Cosi' il colore segue il tema (light/dark/system) senza alcun JS aggiuntivo,
 * anche dopo un toggle successivo al render iniziale.
 */

/** Le 5 serie colore per grafici multi-serie (Line, Bar, Area, ...). */
export const chartColors = [
  'hsl(var(--chart-1))',
  'hsl(var(--chart-2))',
  'hsl(var(--chart-3))',
  'hsl(var(--chart-4))',
  'hsl(var(--chart-5))',
] as const

/** Stroke per <CartesianGrid>: visibile ma discreto in entrambi i temi. */
export const chartGrid = 'hsl(var(--border))'

/** Stroke/tick per <XAxis>/<YAxis>. */
export const chartAxis = 'hsl(var(--muted-foreground))'

/** contentStyle per <Tooltip contentStyle={chartTooltip}>. */
export const chartTooltip = {
  backgroundColor: 'hsl(var(--card))',
  border: '1px solid hsl(var(--border))',
  color: 'hsl(var(--foreground))',
}
