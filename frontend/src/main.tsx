// frontend/src/main.tsx
import { QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { ThemeProvider } from './components/theme-provider'
import './index.css'
import { queryClient } from './lib/queryClient'

// ThemeProvider avvolge tutto: usa fetch diretti (api.get/api.put), non hook
// TanStack Query, quindi non ha bisogno di stare dentro QueryClientProvider —
// lo mettiamo comunque all'esterno perché il tema è una preferenza globale
// dell'app, non legata al routing né al query client.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </React.StrictMode>,
)
