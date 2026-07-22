import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'

interface Account {
  id: number
  name: string
  display_name: string | null
}

export function Accounts() {
  const queryClient = useQueryClient()
  const [editingId, setEditingId] = useState<number | null>(null)
  const [displayName, setDisplayName] = useState('')

  const { data, isLoading } = useQuery<Account[]>({
    queryKey: ['accounts'],
    queryFn: () => api.get<Account[]>('/accounts'),
  })

  const renameMutation = useMutation({
    mutationFn: (vars: { id: number; display_name: string }) =>
      api.patch(`/accounts/${vars.id}`, { display_name: vars.display_name }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      setEditingId(null)
    },
  })

  if (isLoading) return <p>Caricamento...</p>

  return (
    <div>
      <h2 className="mb-4 text-lg font-semibold">Conti</h2>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="py-2">Nome sorgente</th>
            <th>Nome visualizzato</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {data?.map((a) => (
            <tr key={a.id} className="border-b">
              <td className="py-2">{a.name}</td>
              <td>
                {editingId === a.id ? (
                  <input
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    className="rounded border px-2 py-1 text-xs"
                  />
                ) : (
                  a.display_name ?? a.name
                )}
              </td>
              <td className="space-x-2">
                {editingId === a.id ? (
                  <>
                    <Button size="sm" onClick={() => renameMutation.mutate({ id: a.id, display_name: displayName })}>
                      Salva
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setEditingId(null)}>
                      Annulla
                    </Button>
                  </>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setEditingId(a.id)
                      setDisplayName(a.display_name ?? a.name)
                    }}
                  >
                    Rinomina
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {renameMutation.error ? (
        <p className="mt-3 text-destructive">{(renameMutation.error as Error).message}</p>
      ) : null}
    </div>
  )
}
