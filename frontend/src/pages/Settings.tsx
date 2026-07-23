// frontend/src/pages/Settings.tsx
//
// Pagina /impostazioni (F9, ADR-0027). Unico punto di configurazione esposto
// all'utente (CLAUDE.md regola 6): tema, dashboard esterne, parametri ETL,
// backup, AI e stato dei secret. Una sola query alimenta valori e metadati
// (`applies_when`/`source`/`secrets_status`); il tema passa da `useTheme()`
// (gia' applica classe DOM + localStorage + PUT /settings da solo, T9), le
// altre chiavi whitelist si salvano con un'unica PUT /settings.
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { useTheme, type Theme } from '@/components/theme-provider'
import { api } from '@/lib/api'

type SettingSource = 'db' | 'env' | 'default'

interface SettingsItem {
  key: string
  value: string | number | boolean
  source: SettingSource
  applies_when: string
}

interface SecretStatus {
  configured: boolean
}

interface SettingsResponse {
  settings: SettingsItem[]
  secrets_status: Record<string, SecretStatus>
}

interface EditableValues {
  metabase_url: string
  import_min_year: number
  backup_retention: number
  backup_on_startup: boolean
  ai_history_max_turns: number
}

const THEME_OPTIONS: { value: Theme; label: string }[] = [
  { value: 'light', label: 'Chiaro' },
  { value: 'dark', label: 'Scuro' },
  { value: 'system', label: 'Sistema' },
]

const SECRET_FIELDS: { key: string; envVar: string; label: string }[] = [
  { key: 'ai_api_key', envVar: 'AI_API_KEY', label: 'Chiave provider AI' },
  { key: 'google_sa_key_path', envVar: 'GOOGLE_SA_KEY_PATH', label: 'Service account Google Drive' },
  { key: 'gdrive_backup_folder_id', envVar: 'GDRIVE_BACKUP_FOLDER_ID', label: 'Cartella backup Google Drive' },
]

function sourceLabel(source: SettingSource): string {
  switch (source) {
    case 'db':
      return 'salvato'
    case 'env':
      return "variabile d'ambiente"
    default:
      return 'valore predefinito'
  }
}

function findSetting(data: SettingsResponse | undefined, key: string): SettingsItem | undefined {
  return data?.settings.find((item) => item.key === key)
}

function SettingMeta({ item }: { item: SettingsItem | undefined }) {
  if (!item) return null
  return (
    <p className="mt-1 text-xs text-muted-foreground">
      Si applica: {item.applies_when} · Fonte: {sourceLabel(item.source)}
    </p>
  )
}

function parseNumberInput(raw: string): number {
  const next = Number(raw)
  return Number.isNaN(next) ? 0 : next
}

// `backup_retention` e `import_min_year` non ammettono 0/vuoto: 0 in
// `apply_local_retention` (backend/app/backup.py) cancella TUTTO lo storico
// backup locale (`timestamps[0:]`), non "nessuna retention" — nessun default
// silenzioso, il submit va bloccato con un messaggio visibile (Finding 2).
const POSITIVE_INT_FIELDS: { key: keyof EditableValues; label: string }[] = [
  { key: 'backup_retention', label: 'Numero di backup da conservare' },
  { key: 'import_min_year', label: 'Anno minimo import storico' },
]

function validatePositiveInts(values: EditableValues): string | null {
  for (const { key, label } of POSITIVE_INT_FIELDS) {
    const value = values[key] as number
    if (!Number.isFinite(value) || value < 1) {
      return `"${label}" deve essere un numero intero maggiore o uguale a 1.`
    }
  }
  return null
}

export function Settings() {
  const queryClient = useQueryClient()
  const { theme, setTheme } = useTheme()
  const hydrated = useRef(false)
  const [validationError, setValidationError] = useState<string | null>(null)

  const { data, isLoading, error } = useQuery<SettingsResponse>({
    queryKey: ['settings'],
    queryFn: () => api.get<SettingsResponse>('/settings'),
  })

  const [values, setValues] = useState<EditableValues>({
    metabase_url: '',
    import_min_year: new Date().getFullYear(),
    backup_retention: 30,
    backup_on_startup: false,
    ai_history_max_turns: 6,
  })

  // Idrata il form una sola volta al primo caricamento riuscito: un refetch
  // successivo (es. refetchOnWindowFocus, o l'invalidate dopo il salvataggio)
  // non deve sovrascrivere modifiche non ancora salvate dall'utente.
  useEffect(() => {
    if (!data || hydrated.current) return
    setValues({
      metabase_url: String(findSetting(data, 'metabase_url')?.value ?? ''),
      import_min_year: Number(findSetting(data, 'import_min_year')?.value ?? 0),
      backup_retention: Number(findSetting(data, 'backup_retention')?.value ?? 0),
      backup_on_startup: Boolean(findSetting(data, 'backup_on_startup')?.value ?? false),
      ai_history_max_turns: Number(findSetting(data, 'ai_history_max_turns')?.value ?? 0),
    })
    hydrated.current = true
  }, [data])

  const saveMutation = useMutation({
    mutationFn: (payload: EditableValues) => api.put('/settings', payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settings'] }),
  })

  if (isLoading) return <p>Caricamento...</p>
  if (error) return <p className="text-destructive">Errore: {(error as Error).message}</p>

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    const validationMessage = validatePositiveInts(values)
    if (validationMessage) {
      setValidationError(validationMessage)
      return
    }
    setValidationError(null)
    saveMutation.mutate(values)
  }

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold">Impostazioni</h2>

      <section className="rounded-lg border bg-card p-4">
        <h3 className="mb-3 font-semibold">Aspetto</h3>
        <div className="flex gap-2">
          {THEME_OPTIONS.map((option) => (
            <Button
              key={option.value}
              size="sm"
              variant={theme === option.value ? 'default' : 'outline'}
              onClick={() => setTheme(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </div>
        <SettingMeta item={findSetting(data, 'theme')} />
      </section>

      <form onSubmit={handleSubmit} className="space-y-6">
        <section className="rounded-lg border bg-card p-4">
          <h3 className="mb-3 font-semibold">Dashboard esterne</h3>
          <label className="block text-sm">
            URL Metabase
            <input
              value={values.metabase_url}
              onChange={(e) => setValues((v) => ({ ...v, metabase_url: e.target.value }))}
              className="mt-1 block w-full rounded border px-2 py-1 text-xs"
            />
          </label>
          <SettingMeta item={findSetting(data, 'metabase_url')} />
        </section>

        <section className="rounded-lg border bg-card p-4">
          <h3 className="mb-3 font-semibold">Parametri ETL</h3>
          <label className="block text-sm">
            Anno minimo import storico
            <input
              type="number"
              min={1}
              value={values.import_min_year}
              onChange={(e) =>
                setValues((v) => ({ ...v, import_min_year: parseNumberInput(e.target.value) }))
              }
              className="mt-1 block w-32 rounded border px-2 py-1 text-xs"
            />
          </label>
          <SettingMeta item={findSetting(data, 'import_min_year')} />
        </section>

        <section className="rounded-lg border bg-card p-4">
          <h3 className="mb-3 font-semibold">Backup</h3>
          <label className="block text-sm">
            Numero di backup da conservare
            <input
              type="number"
              min={1}
              value={values.backup_retention}
              onChange={(e) =>
                setValues((v) => ({ ...v, backup_retention: parseNumberInput(e.target.value) }))
              }
              className="mt-1 block w-32 rounded border px-2 py-1 text-xs"
            />
          </label>
          <SettingMeta item={findSetting(data, 'backup_retention')} />

          <label className="mt-4 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={values.backup_on_startup}
              onChange={(e) => setValues((v) => ({ ...v, backup_on_startup: e.target.checked }))}
            />
            Backup automatico all'avvio
          </label>
          <SettingMeta item={findSetting(data, 'backup_on_startup')} />
        </section>

        <section className="rounded-lg border bg-card p-4">
          <h3 className="mb-3 font-semibold">AI</h3>
          <label className="block text-sm">
            Turni massimi di cronologia
            <input
              type="number"
              value={values.ai_history_max_turns}
              onChange={(e) =>
                setValues((v) => ({ ...v, ai_history_max_turns: parseNumberInput(e.target.value) }))
              }
              className="mt-1 block w-32 rounded border px-2 py-1 text-xs"
            />
          </label>
          <SettingMeta item={findSetting(data, 'ai_history_max_turns')} />
        </section>

        <div>
          <Button type="submit" disabled={saveMutation.isPending}>
            Salva impostazioni
          </Button>
          {saveMutation.isSuccess && !saveMutation.isPending ? (
            <span className="ml-3 text-sm text-success">Impostazioni salvate.</span>
          ) : null}
          {validationError ? <p className="mt-2 text-destructive">{validationError}</p> : null}
          {saveMutation.error ? (
            <p className="mt-2 text-destructive">{(saveMutation.error as Error).message}</p>
          ) : null}
        </div>
      </form>

      <section className="rounded-lg border bg-card p-4">
        <h3 className="mb-3 font-semibold">Secret</h3>
        <div className="space-y-3">
          {SECRET_FIELDS.map((field) => {
            const configured = data?.secrets_status[field.key]?.configured ?? false
            return (
              <div key={field.key} className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-sm">{field.label}</p>
                  <p className="text-xs text-muted-foreground">
                    Imposta <code className="rounded bg-muted px-1 py-0.5">{field.envVar}</code> nel
                    file <code className="rounded bg-muted px-1 py-0.5">.env</code>
                  </p>
                </div>
                <span
                  className={
                    configured
                      ? 'shrink-0 rounded px-2 py-1 text-xs text-success bg-success/10'
                      : 'shrink-0 rounded px-2 py-1 text-xs text-muted-foreground bg-muted'
                  }
                >
                  {configured ? 'Configurato' : 'Non configurato'}
                </span>
              </div>
            )
          })}
        </div>
      </section>
    </div>
  )
}
