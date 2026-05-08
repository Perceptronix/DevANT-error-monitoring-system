import { useMemo } from 'react'

interface Props {
  snapshot: any | null
}

const STAGES = [
  'Repository Ingestion',
  'Workflow Discovery',
  'Deployment Analysis',
  'Observability Analysis',
  'Topology Inference',
  'Regression Risk Analysis',
  'Operational Scoring',
  'Confidence Calibration',
  'Final Operational Synthesis',
]

export default function PipelineTimeline({ snapshot }: Props) {
  const items = useMemo(() => {
    const partial = snapshot?.partial || snapshot?.result_snapshot?.partial || {}
    return STAGES.map((name) => {
      const key = name.toLowerCase().replace(/ /g, '_')
      const entry = partial[key] || partial[name] || null
      const ts = entry?.last_event?.timestamp || entry?.last_event?.partial_result?.timestamp || null
      const status = entry?.state || (entry?.status ? String(entry.status).toLowerCase() : 'pending')
      return { name, status, ts }
    })
  }, [snapshot])

  return (
    <section className="rounded-xl border border-border bg-card p-4 space-y-3">
      <h2 className="font-semibold">Pipeline Timeline</h2>
      <div className="space-y-2 text-sm">
        {items.map((it) => (
          <div key={it.name} className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-2 h-2 rounded-full" style={{ background: it.status === 'completed' ? '#10b981' : it.status === 'running' || it.status === 'partial' ? '#0ea5e9' : '#94a3b8' }} />
              <div>{it.name}</div>
            </div>
            <div className="text-xs text-muted-foreground">{it.ts ? String(it.ts).slice(0, 19).replace('T', ' ') : it.status}</div>
          </div>
        ))}
      </div>
    </section>
  )
}
