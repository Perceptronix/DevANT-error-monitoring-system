import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Badge } from '@/components/ui/badge'

type StageState = 'pending' | 'running' | 'completed' | 'failed' | 'partial'

interface StageData {
  id: string
  name: string
  state?: StageState
  progress?: number // 0..1
  evidence?: Array<{ title: string; details?: string }>
  note?: string
}

interface Props {
  snapshot: any | null
}

const DEFAULT_STAGES = [
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

export function normalize(s: string) {
  if (!s) return s
  const step = s.replace(/[-_]+/g, ' ').replace(/([a-z0-9])([A-Z])/g, '$1 $2')
  return step
    .split(' ')
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(' ')
}

function stateVariant(s?: StageState) {
  if (!s || s === 'pending') return 'outline'
  if (s === 'running' || s === 'partial') return 'secondary'
  if (s === 'completed') return 'default'
  return 'destructive'
}

export default function RepositoryPipeline({ snapshot }: Props) {
  

  const pipeline: StageData[] = useMemo(() => {
    const data: StageData[] = []
    const partial = snapshot?.partial ?? snapshot?.result_snapshot?.partial

    // If backend supplies explicit array pipeline, use it
    if (partial?.pipeline && Array.isArray(partial.pipeline)) {
      for (const s of partial.pipeline) {
        data.push({
          id: s.id || s.name,
          name: normalize(s.name || s.id),
          state: s.state,
          progress: typeof s.progress === 'number' ? s.progress : undefined,
          evidence: s.evidence,
          note: s.note,
        })
      }
      // ensure all default stages present
      for (const name of DEFAULT_STAGES) {
        if (!data.find((d) => d.name === name)) data.push({ id: name, name, state: 'pending' })
      }
      return data
    }

    // If partial is object keyed by step id/name, map onto DEFAULT_STAGES in order
    if (partial && typeof partial === 'object') {
      for (const name of DEFAULT_STAGES) {
        // try possible keys: normalized lower, snake, lower
        const keys = [
          name.toLowerCase().replace(/ /g, '_'),
          name.toLowerCase().replace(/ /g, '-'),
          name.toLowerCase(),
        ]
        let entry: any = undefined
        for (const k of keys) {
          if (Object.prototype.hasOwnProperty.call(partial, k)) {
            entry = partial[k]
            break
          }
        }

        if (entry) {
          data.push({
            id: name,
            name,
            state: entry.state || (entry.status as StageState) || 'partial',
            progress: typeof entry.progress === 'number' ? entry.progress : undefined,
            evidence: entry.evidence || entry.data?.evidence || undefined,
            note: entry.note || entry.reasoning || entry.data?.note,
          })
        } else {
          data.push({ id: name, name, state: 'pending' })
        }
      }
      return data
    }

    // fallback: no partial info
    return DEFAULT_STAGES.map((name) => ({ id: name, name, state: 'pending' as StageState }))
  }, [snapshot])

  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  return (
    <section className="rounded-xl border border-border bg-card p-4 space-y-3">
      <h2 className="font-semibold">Repository Operational Analysis Pipeline</h2>

      <div className="space-y-2">
        {pipeline.map((stage) => (
          <div key={stage.id} className="rounded-md border border-border p-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <button
                  className="flex items-center gap-2 text-sm"
                  onClick={() => setExpanded((s) => ({ ...s, [stage.id]: !s[stage.id] }))}
                >
                  {expanded[stage.id] ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                  <span className="font-medium">{stage.name}</span>
                </button>
                <Badge variant={stateVariant(stage.state)}>{stage.state || 'pending'}</Badge>
              </div>

              <div className="text-xs text-muted-foreground">{stage.note || (stage.progress ? `${Math.round((stage.progress ?? 0) * 100)}%` : '')}</div>
            </div>

            {expanded[stage.id] && (
              <div className="mt-3 text-sm space-y-2">
                {stage.evidence && stage.evidence.length > 0 ? (
                  stage.evidence.map((e, i) => (
                    <div key={i} className="rounded-md border border-border p-2">
                      <div className="font-medium">{e.title}</div>
                      {e.details && <div className="text-xs text-muted-foreground">{e.details}</div>}
                    </div>
                  ))
                ) : (
                  <div className="text-xs text-muted-foreground">No evidence surfaced yet for this stage.</div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
