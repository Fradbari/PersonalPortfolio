import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { api, ApiError } from '@/lib/api'

interface BackupsResponse {
  backups: string[] // timestamp, es. "20260715_143022" — NON filename (backend/app/backup.py::list_local_backups)
}

// Contratto backend/app/drive.py::ProbeResult (ADR-0035, autenticazione OAuth utente).
// La UI mostra `outcome` e `message` cosi' come arrivano, senza logica per-esito:
// il rimedio e' gia' nel messaggio del backend. Esiti possibili: ok, auth_missing,
// auth_invalid, folder_id_missing, auth_expired, folder_not_found, permission_denied,
// api_disabled, quota_exceeded, timeout, network_error, unexpected.
interface ProbeResult {
  ok: boolean
  outcome: string
  stage: string | null
  message: string
  google_status: number | null
  google_reason: string | null
  probe_written: boolean
  probe_deleted: boolean
  orphans_removed: number
  elapsed_ms: number
}

interface LastBackup {
  at: string
  trigger: 'manual' | 'startup'
  local_ok: boolean
  drive_uploaded: boolean
  drive_outcome: string | null
  message: string | null
}

interface LastBackupResponse {
  last: LastBackup | null
}

export function Backup() {
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery<BackupsResponse>({
    queryKey: ['backups'],
    queryFn: () => api.get<BackupsResponse>('/backup'),
  })

  const { data: lastData } = useQuery<LastBackupResponse>({
    queryKey: ['backup', 'last'],
    queryFn: () => api.get<LastBackupResponse>('/backup/last'),
  })
  const last = lastData?.last ?? null

  const refreshAfterBackup = () => {
    queryClient.invalidateQueries({ queryKey: ['backups'] })
    queryClient.invalidateQueries({ queryKey: ['backup', 'last'] })
  }

  const backupNowMutation = useMutation({
    mutationFn: () => api.post('/backup'),
    onSuccess: refreshAfterBackup,
    onError: refreshAfterBackup,
  })

  // Solo al click: nessuna query/effect automatica su gdrive-test.
  const driveTestMutation = useMutation<ProbeResult, Error>({
    mutationFn: () => api.post<ProbeResult>('/backup/gdrive-test'),
  })
  const probe = driveTestMutation.data
  const driveTestError = driveTestMutation.error
  const driveTestErrorText = driveTestError
    ? driveTestError instanceof ApiError && driveTestError.status === 409
      ? 'Test già in corso.'
      : 'Impossibile eseguire il test di connessione a Drive.'
    : null

  const restoreMutation = useMutation({
    mutationFn: (filename: string) => api.post('/backup/restore', { filename, confirm: true }),
  })

  return (
    <div>
      <h2 className="mb-4 text-lg font-semibold">Backup</h2>

      <div role="status" aria-live="polite" className="mb-4 rounded border p-3 text-sm">
        <p className="font-medium">Ultimo backup</p>
        {last === null ? (
          <p className="text-muted-foreground">Nessun backup in questa sessione</p>
        ) : (
          <div className="space-y-1">
            <p>
              {new Date(last.at).toLocaleString('it-IT')} —{' '}
              {last.trigger === 'startup' ? "all'avvio" : 'manuale'}
            </p>
            <p>
              Locale: {last.local_ok ? 'ok' : 'fallito'}
              {last.drive_uploaded ? ' · Drive: caricato' : ''}
            </p>
            {last.message || !last.local_ok ? (
              <p
                className={
                  last.local_ok
                    ? 'rounded border border-warning bg-warning/15 p-2 text-foreground'
                    : 'rounded border border-destructive bg-destructive/15 p-2 text-foreground'
                }
              >
                {last.message ?? last.drive_outcome ?? 'Backup fallito.'}
              </p>
            ) : null}
          </div>
        )}
      </div>

      <Button disabled={backupNowMutation.isPending} onClick={() => backupNowMutation.mutate()}>
        Backup ora
      </Button>
      {backupNowMutation.data ? (
        <pre className="mt-3 rounded bg-muted p-3 text-xs">{JSON.stringify(backupNowMutation.data, null, 2)}</pre>
      ) : null}

      <h3 className="mb-2 mt-6 font-semibold">Google Drive</h3>
      <Button
        variant="outline"
        disabled={driveTestMutation.isPending}
        onClick={() => driveTestMutation.mutate()}
      >
        {driveTestMutation.isPending ? 'Test in corso…' : 'Test connessione Drive'}
      </Button>
      <p className="mt-2 text-xs text-muted-foreground">
        Crea, rilegge e cancella un file di prova di pochi byte nella cartella Drive configurata. Può richiedere fino a due minuti.
      </p>
      <div role="status" aria-live="polite" className="mt-3 space-y-2 text-sm">
        {probe ? (
          <>
            <span
              className={
                probe.ok
                  ? 'inline-block rounded bg-success px-2 py-0.5 text-xs font-medium text-success-foreground'
                  : 'inline-block rounded bg-destructive px-2 py-0.5 text-xs font-medium text-destructive-foreground'
              }
            >
              {probe.ok ? 'Connessione OK' : 'Connessione fallita'}
            </span>
            <p>{probe.message}</p>
            <p className="text-xs text-muted-foreground">
              outcome: {probe.outcome}
              {probe.stage ? ` · stage: ${probe.stage}` : ''}
              {probe.google_status !== null ? ` · google_status: ${probe.google_status}` : ''}
              {probe.google_reason ? ` · google_reason: ${probe.google_reason}` : ''}
            </p>
            {probe.probe_written && !probe.probe_deleted ? (
              <p className="rounded bg-warning/15 p-2 text-warning-foreground">
                Il file di prova potrebbe essere rimasto nella cartella Drive: verrà rimosso al prossimo test.
              </p>
            ) : null}
          </>
        ) : null}
        {driveTestErrorText ? (
          <p className="rounded border border-destructive bg-destructive/15 p-2 text-foreground">{driveTestErrorText}</p>
        ) : null}
      </div>

      <h3 className="mb-2 mt-6 font-semibold">Backup disponibili</h3>
      {isLoading ? <p>Caricamento...</p> : null}
      <ul className="space-y-2 text-sm">
        {data?.backups.map((ts) => {
          const filename = `portfolio_backup_${ts}.db`
          return (
            <li key={ts} className="flex items-center justify-between rounded border px-3 py-2">
              <span>{ts}</span>
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button size="sm" variant="destructive">
                    Restore
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogTitle>Ripristinare da {ts}?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Sovrascrive il DB live corrente. Operazione distruttiva e non reversibile (ADR-0018).
                  </AlertDialogDescription>
                  <div className="mt-4 flex justify-end gap-2">
                    <AlertDialogCancel asChild>
                      <Button variant="outline">Annulla</Button>
                    </AlertDialogCancel>
                    <AlertDialogAction asChild>
                      <Button variant="destructive" onClick={() => restoreMutation.mutate(filename)}>
                        Conferma restore
                      </Button>
                    </AlertDialogAction>
                  </div>
                </AlertDialogContent>
              </AlertDialog>
            </li>
          )
        })}
      </ul>
      {restoreMutation.data ? (
        <p className="mt-3 text-success">Restore completato: {JSON.stringify(restoreMutation.data)}</p>
      ) : null}
      {restoreMutation.error ? <p className="mt-3 text-destructive">{(restoreMutation.error as Error).message}</p> : null}
    </div>
  )
}
