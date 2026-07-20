# Frontend — Personal Portfolio

UI React del progetto Personal Portfolio (7 pagine: Dashboard, Transazioni, Import, Categorie
pending, Conti, Backup, Assistente AI). In produzione **non gira standalone**: viene buildata
(`vite build`) e servita dal container FastAPI (`backend/`) sulla stessa porta 8000 — vedi
[ADR-0019](../docs/DECISIONS.md). La porta 5173 sotto è solo per sviluppo locale (`npm run dev`).

## Stato fase corrente (2026-07-20)
F5 (questa UI) completata. F0-F6 + F-DEBT completate; F7 (Raspberry Pi arm64) in preparazione.
Guida funzionale utente: [../docs/USER_GUIDE.md](../docs/USER_GUIDE.md). Guida avvio:
[../docs/GETTING_STARTED.md](../docs/GETTING_STARTED.md).

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
