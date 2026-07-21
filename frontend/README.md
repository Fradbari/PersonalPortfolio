# Frontend — Personal Portfolio

UI React del progetto Personal Portfolio (7 pagine: Dashboard, Transazioni, Import, Categorie
pending, Conti, Backup, Assistente AI). In produzione **non gira standalone**: viene buildata
(`vite build`) e servita dal container FastAPI (`backend/`) sulla stessa porta 8000 — vedi
[ADR-0019](../docs/DECISIONS.md). La porta 5173 sotto è solo per sviluppo locale (`npm run dev`).

## Stato fase corrente (2026-07-21)
F5 (questa UI) completata. F0-F6 + F-DEBT completate; F7 (Raspberry Pi arm64) ◐ parcheggiata in
attesa hardware. **Fase corrente: Blocco A (F8 dark mode + F9 settings)** — nessun codice F8-F14
ancora scritto. Guida funzionale utente: [../docs/USER_GUIDE.md](../docs/USER_GUIDE.md). Guida
avvio: [../docs/GETTING_STARTED.md](../docs/GETTING_STARTED.md).

## In arrivo con F8-F13

Pianificato il 2026-07-21 (spec
[../docs/superpowers/specs/2026-07-21-f8-f14-roadmap-design.md](../docs/superpowers/specs/2026-07-21-f8-f14-roadmap-design.md),
ADR-0026 → ADR-0032).

**Sistema di temi (F8, ADR-0026).** Oggi il tema scuro non esiste per niente: `tailwind.config.js`
non dichiara `darkMode`, `index.css` è tre righe senza una sola CSS variable, e ci sono 31 classi
colore hardcoded su 11 file più 5 esadecimali passati a Recharts in `pages/Dashboard.tsx`. Il
lavoro previsto:

- `darkMode: 'class'` e token semantici in `src/index.css` (`:root` + `.dark`, formato **HSL
  triplo**, sintassi Tailwind v3): `--background`, `--foreground`, `--card`, `--muted`, `--border`,
  `--primary`, `--destructive`, `--success`, `--chart-1 … --chart-5`;
- `ThemeProvider` (`light | dark | system`) più uno **script inline in `index.html`** che applica la
  classe **prima** del bundle — senza, ogni reload lampeggia bianco;
- conversione di tutte le classi hardcoded in utility semantiche (`bg-background`,
  `text-foreground`, `border-border`);
- **`src/lib/chart-config.ts` condiviso**: nessun grafico dichiara colori propri. Un `stroke="#..."`
  in una PR è un difetto, non una scelta.

**Vincoli di stack, deliberati.** Tailwind resta a **v3.4.19** — nessuna migrazione a v4 in questa
fase. La CLI shadcn resta **non inizializzata** (nessun `components.json`): i componenti nuovi, come
`ChartContainer`/`ChartTooltip`, si portano a mano in `components/ui/`, come già `button.tsx` e
`alert-dialog.tsx`. Recharts è già `^3.9.2`, quindi i token si riferiscono come `var(--chart-N)`.

**Pagine e funzionalità nuove**

- **`/settings`** (ottava pagina, F9): unico punto di configurazione dell'app — nessuna altra pagina
  costruisce un proprio pannello di impostazioni. I secret compaiono solo come badge "configurato /
  non configurato" con la riga `.env` da usare, **mai come campo di input**. Accanto a ogni campo va
  indicato quando la modifica ha effetto (subito o al riavvio).
- **Inserimento manuale transazione** (F11): form con validazione per campo; in caso di duplicato il
  backend risponde 409 mostrando la transazione gemella, e la UI chiede conferma prima di forzare.
- **Filtri avanzati** (F12): periodo, categoria, conto, importo, tipo e ricerca full-text. Lo stato
  dei filtri vive in `useSearchParams` e alimenta la `queryKey` di TanStack Query — **niente
  `useState` parallelo all'URL**, che divergerebbe al primo back del browser. Ogni combinazione di
  filtri diventa un permalink.
- **Pannelli dashboard** (F13): saldo cumulato, cash flow mensile, donut spese per categoria, trend
  risparmio, confronto mese su mese, quattro KPI card. Tutti sul `chartConfig` condiviso.

**Vincolo di nomenclatura**: la parola "patrimonio" non compare in UI, tooltip, titoli o nomi di
campo. Il dato disponibile è un **saldo cumulato** di entrate e uscite — non esistono asset né
passività nel database, e un'etichetta approssimata resta comunque quella su cui l'utente decide.

---

# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.
