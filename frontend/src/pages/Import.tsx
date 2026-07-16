import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { uploadFile } from '@/lib/api'

export function Import() {
  const [myFinanceFile, setMyFinanceFile] = useState<File | null>(null)
  const [historicalFile, setHistoricalFile] = useState<File | null>(null)
  const [dryRunResult, setDryRunResult] = useState<unknown>(null)

  const myFinanceMutation = useMutation({
    mutationFn: (file: File) => uploadFile('/import/my-finance', file),
  })

  const dryRunMutation = useMutation({
    mutationFn: (file: File) => uploadFile('/import/historical/dry-run', file),
    onSuccess: (data) => setDryRunResult(data),
  })

  const commitMutation = useMutation({
    mutationFn: (file: File) => uploadFile('/import/historical/commit', file),
  })

  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-2 text-lg font-semibold">Import My Finance (mensile)</h2>
        <input type="file" accept=".xlsx" onChange={(e) => setMyFinanceFile(e.target.files?.[0] ?? null)} />
        <Button
          className="ml-3"
          disabled={!myFinanceFile || myFinanceMutation.isPending}
          onClick={() => myFinanceFile && myFinanceMutation.mutate(myFinanceFile)}
        >
          Importa
        </Button>
        {myFinanceMutation.data ? (
          <pre className="mt-3 rounded bg-gray-100 p-3 text-xs">{JSON.stringify(myFinanceMutation.data, null, 2)}</pre>
        ) : null}
        {myFinanceMutation.error ? (
          <p className="mt-2 text-red-600">{(myFinanceMutation.error as Error).message}</p>
        ) : null}
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Import storico (master sheet)</h2>
        <input type="file" accept=".xlsx" onChange={(e) => setHistoricalFile(e.target.files?.[0] ?? null)} />
        <div className="mt-3 space-x-2">
          <Button
            variant="outline"
            disabled={!historicalFile || dryRunMutation.isPending}
            onClick={() => historicalFile && dryRunMutation.mutate(historicalFile)}
          >
            Dry-run
          </Button>
          <Button
            variant="destructive"
            disabled={!historicalFile || !dryRunResult || commitMutation.isPending}
            onClick={() => historicalFile && commitMutation.mutate(historicalFile)}
          >
            Commit (dopo validazione dry-run)
          </Button>
        </div>
        {dryRunResult ? (
          <pre className="mt-3 rounded bg-gray-100 p-3 text-xs">{JSON.stringify(dryRunResult, null, 2)}</pre>
        ) : null}
        {commitMutation.data ? (
          <pre className="mt-3 rounded bg-green-50 p-3 text-xs">{JSON.stringify(commitMutation.data, null, 2)}</pre>
        ) : null}
      </section>
    </div>
  )
}
