import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'

interface Pending {
  id: number
  source: string
  source_name: string
  created_at: string | null
}

export function CategoriesPending() {
  const queryClient = useQueryClient()
  const [assignments, setAssignments] = useState<Record<number, string>>({})

  const { data, isLoading } = useQuery<Pending[]>({
    queryKey: ['categories-pending'],
    queryFn: () => api.get<Pending[]>('/categories/pending'),
  })

  const resolveMutation = useMutation({
    mutationFn: (vars: { id: number; category_name: string }) =>
      api.post(`/categories/pending/${vars.id}/resolve`, { category_name: vars.category_name }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['categories-pending'] }),
  })

  if (isLoading) return <p>Caricamento...</p>

  return (
    <div>
      <h2 className="mb-4 text-lg font-semibold">Categorie pending</h2>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="py-2">Fonte</th>
            <th>Nome sorgente</th>
            <th>Assegna a categoria</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {data?.map((p) => (
            <tr key={p.id} className="border-b">
              <td className="py-2">{p.source}</td>
              <td>{p.source_name}</td>
              <td>
                <input
                  value={assignments[p.id] ?? ''}
                  onChange={(e) => setAssignments((a) => ({ ...a, [p.id]: e.target.value }))}
                  placeholder="es. Alimentari"
                  className="rounded border px-2 py-1 text-xs"
                />
              </td>
              <td>
                <Button
                  size="sm"
                  disabled={!assignments[p.id] || resolveMutation.isPending}
                  onClick={() => resolveMutation.mutate({ id: p.id, category_name: assignments[p.id] })}
                >
                  Assegna
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {data?.length === 0 ? <p className="text-muted-foreground">Nessuna categoria in coda.</p> : null}
      {resolveMutation.error ? (
        <p className="mt-3 text-destructive">{(resolveMutation.error as Error).message}</p>
      ) : null}
    </div>
  )
}
