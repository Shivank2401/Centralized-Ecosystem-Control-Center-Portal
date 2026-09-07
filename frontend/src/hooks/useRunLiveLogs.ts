import { useEffect, useRef, useState } from 'react'
import type { PipelineRunStatus, RunLogsPayload } from '@/types'

export function useRunLiveLogs(runId: string | undefined) {
  const [text, setText] = useState('')
  const [status, setStatus] = useState<PipelineRunStatus | null>(null)
  const [progress, setProgress] = useState(0)
  const [currentReport, setCurrentReport] = useState<string | null>(null)
  const [completed, setCompleted] = useState<string[]>([])
  const [connected, setConnected] = useState(false)
  const buffer = useRef('')

  useEffect(() => {
    if (!runId) return
    setText('')
    buffer.current = ''
    setConnected(false)

    const es = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`)

    const onUpdate = (ev: MessageEvent) => {
      setConnected(true)
      try {
        const payload = JSON.parse(ev.data) as RunLogsPayload
        if (payload.text) {
          buffer.current += payload.text
          setText(buffer.current)
        }
        setStatus(payload.status)
        setProgress(payload.progress)
        setCurrentReport(payload.current_report ?? null)
        setCompleted(payload.completed_reports ?? [])
      } catch {
        /* ignore malformed */
      }
    }

    es.addEventListener('update', onUpdate)
    es.addEventListener('done', (ev) => {
      onUpdate(ev as MessageEvent)
      es.close()
    })
    es.onerror = () => {
      setConnected(false)
    }

    return () => {
      es.close()
    }
  }, [runId])

  return { text, status, progress, currentReport, completed, connected }
}
