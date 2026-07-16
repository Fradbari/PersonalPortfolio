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
import { api } from '@/lib/api'

interface BackupsResponse {
  backups: string[] // timestamp, es. "20260715_143022" — NON filename (backend/app/backup.py::list_local_backups)
}

export function Backup() {
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery<BackupsResponse>({
    queryKey: ['backups'],
    queryFn: () => api.get<BackupsResponse>('/backup'),
  })

  const backupNowMutation = useMutation({
    mutationFn: () => api.post('/backup'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['backups'] }),
  })

  const restoreMutation = useMutation({
    mutationFn: (filename: string) => api.post('/backup/restore', { filename, confirm: true }),
  })

  return (
    <div>
      <h2 className="mb-4 text-lg font-semibold">Backup</h2>
      <Button disabled={backupNowMutation.isPending} onClick={() => backupNowMutation.mutate()}>
        Backup ora
      </Button>
      {backupNowMutation.data ? (
        <pre className="mt-3 rounded bg-gray-100 p-3 text-xs">{JSON.stringify(backupNowMutation.data, null, 2)}</pre>
      ) : null}

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
        <p className="mt-3 text-green-700">Restore completato: {JSON.stringify(restoreMutation.data)}</p>
      ) : null}
      {restoreMutation.error ? <p className="mt-3 text-red-600">{(restoreMutation.error as Error).message}</p> : null}
    </div>
  )
}
