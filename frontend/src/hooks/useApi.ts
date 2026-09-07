import { useQuery } from '@tanstack/react-query'
import { api } from '@/services/api'

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 30_000,
    retry: 1,
  })
}

export function useClients() {
  return useQuery({ queryKey: ['clients'], queryFn: api.clients })
}

export function useGeographies(client: string | undefined) {
  return useQuery({
    queryKey: ['geographies', client],
    queryFn: () => api.geographies(client!),
    enabled: Boolean(client),
  })
}

export function useStages(clients?: string[]) {
  const key = clients?.slice().sort().join(',') ?? 'all'
  return useQuery({
    queryKey: ['stages', key],
    queryFn: () => api.stages(clients),
  })
}

export function useReports(opts?: { client?: string[]; stage?: string; enabledOnly?: boolean }) {
  return useQuery({
    queryKey: ['reports', opts?.client?.slice().sort().join(','), opts?.stage, opts?.enabledOnly],
    queryFn: () => api.reports(opts),
  })
}

export function useSequences() {
  return useQuery({ queryKey: ['sequences'], queryFn: api.sequences })
}

export function useRuns(opts?: { limit?: number; status?: string; client?: string }) {
  return useQuery({
    queryKey: ['runs', opts?.limit, opts?.status, opts?.client],
    queryFn: () => api.runs(opts),
    refetchInterval: 5000,
  })
}

export function useActiveRun() {
  return useQuery({
    queryKey: ['runs', 'active'],
    queryFn: api.activeRun,
    refetchInterval: 2000,
  })
}

export function useRun(runId: string | undefined) {
  return useQuery({
    queryKey: ['runs', runId],
    queryFn: () => api.run(runId!),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'QUEUED' || status === 'RUNNING') return 2000
      return false
    },
  })
}
