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
      // '/backup': la collisione di path ESATTO con la pagina SPA non esiste piu' da
      // quando questa e' su '/backup-restore' (ADR-0033). Resta pero' una collisione di
      // PREFISSO: il matching di Vite e' "path.startsWith(chiave)", quindi la chiave
      // '/backup' come stringa semplice intercetterebbe anche '/backup-restore' (che
      // inizia per '/backup') e la instraderebbe erroneamente al backend invece di
      // lasciarla al fallback SPA di Vite. bypass esclude solo quell'esatta route SPA;
      // l'endpoint reale e i suoi sotto-path ('/backup', '/backup/restore') passano
      // regolarmente al backend.
      '/backup': {
        target: 'http://localhost:8000',
        bypass: (req) => (req.url === '/backup-restore' ? req.url : undefined),
      },
      '/settings': 'http://localhost:8000',
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
