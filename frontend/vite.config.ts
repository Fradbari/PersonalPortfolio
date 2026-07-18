import path from 'path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    proxy: {
      '/transactions': 'http://localhost:8000',
      '/accounts': 'http://localhost:8000',
      '/insights': 'http://localhost:8000',
      '/categories': 'http://localhost:8000',
      // DEBT-04: il bare '/import' collideva con la pagina SPA "/import" (stesso
      // path esatto) — un reload diretto veniva intercettato dal proxy e inoltrato
      // al backend, che non ha un handler GET "/import" esatto -> 404 invece della
      // SPA. Fix: nessun endpoint reale e' mai bare "/import" (sempre
      // "/import/my-finance" o "/import/historical/*"), quindi proxare solo i
      // sotto-path specifici elimina la collisione senza perdere copertura API.
      '/import/my-finance': 'http://localhost:8000',
      '/import/historical': 'http://localhost:8000',
      // '/backup' e' un caso diverso: gli endpoint reali GET/POST /backup sono
      // BARE (stesso path esatto della pagina SPA "/backup", non un sotto-path) —
      // non esiste un pattern piu' specifico da restringere senza perdere quelle
      // due route. Fix: bypass basato su Accept header. Una navigazione/reload
      // reale del browser richiede "text/html" -> bypassa il proxy, lascia servire
      // la SPA da Vite. Le fetch() della SPA (TanStack Query) richiedono
      // "application/json" -> proxate normalmente al backend.
      '/backup': {
        target: 'http://localhost:8000',
        bypass: (req) => {
          if (req.headers.accept?.includes('text/html')) {
            return req.url
          }
        },
      },
      '/health': 'http://localhost:8000',
      // '/ai': prefisso API per POST /ai/query (F6). La pagina SPA e' su
      // '/assistente-ai', stringa diversa che non inizia per '/ai' (il secondo
      // carattere e' 's', non 'i') -> nessuna collisione per prefisso come in
      // ADR-0022, non serve il pattern bypass usato per '/backup'.
      '/ai': 'http://localhost:8000',
    },
  },
  build: { outDir: 'dist' },
})
