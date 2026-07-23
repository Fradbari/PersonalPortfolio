// frontend/src/components/theme-provider.tsx
//
// Tema light/dark/system (F8, ADR-0026/0030). Persistenza doppia:
//   - localStorage: cache locale, applicata subito allo script anti-FOUC in
//     index.html (prima ancora che React monti) e da qui in poi.
//   - DB (`/settings`, chiave whitelist "theme", F9/ADR-0027): fonte di
//     verità, riletta al mount per riallineare eventuali altre sessioni/device.
//
// Vincolo di degradazione: il tema NON deve mai dipendere dalla disponibilità
// del backend. Se `/settings` è irraggiungibile, il tema resta quello già
// applicato da localStorage — l'errore è solo loggato (console.warn), mai
// rilanciato, mai bloccante per il render dell'app.
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from '@/lib/api'

export type Theme = 'light' | 'dark' | 'system'
type ResolvedTheme = 'light' | 'dark'

// Chiave dedicata (non "theme" generico) per evitare collisioni con altre app
// sviluppate sullo stesso host/porta in localhost. Usata anche dallo script
// anti-FOUC inline in frontend/index.html: se cambia qui, va cambiata anche lì.
export const THEME_STORAGE_KEY = 'personal-portfolio:theme'

const DARK_MEDIA_QUERY = '(prefers-color-scheme: dark)'

interface SettingsListItem {
  key: string
  value: unknown
}

interface SettingsResponse {
  settings: SettingsListItem[]
}

function isTheme(value: unknown): value is Theme {
  return value === 'light' || value === 'dark' || value === 'system'
}

function readStoredTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
    return isTheme(stored) ? stored : 'system'
  } catch {
    // localStorage indisponibile (es. modalità privata con quota 0): system
    // resta un default sicuro, coerente con lo script anti-FOUC.
    return 'system'
  }
}

function systemPrefersDark(): boolean {
  return window.matchMedia(DARK_MEDIA_QUERY).matches
}

function resolveTheme(theme: Theme): ResolvedTheme {
  return theme === 'system' ? (systemPrefersDark() ? 'dark' : 'light') : theme
}

function applyThemeClass(theme: Theme): void {
  document.documentElement.classList.toggle('dark', resolveTheme(theme) === 'dark')
}

function persistTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    // Non bloccante: il tema resta comunque applicato in memoria/DOM per la
    // sessione corrente, semplicemente non sopravvive a un reload.
  }
}

interface ThemeContextValue {
  theme: Theme
  resolvedTheme: ResolvedTheme
  setTheme: (theme: Theme) => void
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => readStoredTheme())

  // Riapplica la classe ad ogni cambio di tema (idempotente rispetto allo
  // script anti-FOUC, che l'ha già applicata prima del mount di React).
  useEffect(() => {
    applyThemeClass(theme)
  }, [theme])

  // DB come fonte di verità: al mount, prova a riallineare con /settings.
  // Se la chiamata fallisce (rete/backend giù) il tema resta quello già
  // applicato da localStorage — nessuna eccezione non gestita, nessun blocco
  // del render (vincolo di degradazione).
  useEffect(() => {
    let cancelled = false
    api
      .get<SettingsResponse>('/settings')
      .then((data) => {
        if (cancelled) return
        const dbValue = data.settings?.find((item) => item.key === 'theme')?.value
        if (isTheme(dbValue)) {
          setThemeState((current) => {
            if (dbValue === current) return current
            persistTheme(dbValue)
            return dbValue
          })
        }
      })
      .catch((error) => {
        console.warn(
          '[theme-provider] impossibile leggere /settings, mantengo il tema locale:',
          error,
        )
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Se il tema corrente è "system", segue i cambi di preferenza del SO
  // mentre l'app resta aperta. Cleanup del listener alla dismissione/cambio.
  useEffect(() => {
    if (theme !== 'system') return
    const mediaQuery = window.matchMedia(DARK_MEDIA_QUERY)
    const handleChange = () => applyThemeClass('system')
    mediaQuery.addEventListener('change', handleChange)
    return () => mediaQuery.removeEventListener('change', handleChange)
  }, [theme])

  const setTheme = (next: Theme) => {
    // Ottimistico: stato, classe DOM e cache locale subito, mai in attesa
    // della rete. La PUT è "best effort": se fallisce il tema resta comunque
    // applicato localmente (localStorage è la verità locale finché l'API non
    // torna) — nessun rollback della UI, nessun blocco dell'interazione.
    setThemeState(next)
    applyThemeClass(next)
    persistTheme(next)
    api.put('/settings', { theme: next }).catch((error) => {
      console.warn('[theme-provider] impossibile salvare il tema su /settings:', error)
    })
  }

  return (
    <ThemeContext.Provider value={{ theme, resolvedTheme: resolveTheme(theme), setTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext)
  if (!context) {
    throw new Error('useTheme deve essere usato dentro <ThemeProvider>')
  }
  return context
}
