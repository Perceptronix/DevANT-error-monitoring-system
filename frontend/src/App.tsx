import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, AlertTriangle, Network, Search, Square, Wifi, WifiOff } from 'lucide-react'
import RepositoryPipeline from '@/components/RepositoryPipeline'
import PipelineTimeline from '@/components/PipelineTimeline'
import useSSE from '@/hooks/useSSE'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { isTerminalState, shouldApplySnapshot } from '@/lib/runSnapshot'

type JobState =
  | 'PENDING'
  | 'INITIALIZING'
  | 'INGESTING'
  | 'ANALYZING'
  | 'SCORING'
  | 'FINALIZING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'

interface RunSnapshot {
  run_id: string
  repo_url: string
  state: JobState
  transitions: Array<{ state: JobState; at: string; note?: string }>
  partial?: Record<string, unknown>
  result_snapshot?: {
    scanned?: boolean
    error?: string | null
    evidence?: Record<string, unknown>
    topology?: { services?: Array<{ name?: string; path?: string }>; edges?: Array<{ from: string; to: string }> }
    scores?: Record<string, number>
  } | null
  error?: string | null
}

function scoreBadgeVariant(score: number | undefined): 'default' | 'secondary' | 'outline' | 'destructive' {
  if (score === undefined) return 'outline'
  if (score >= 0.7) return 'default'
  if (score >= 0.45) return 'secondary'
  if (score >= 0.2) return 'outline'
  return 'destructive'
}

function stateVariant(state: JobState | undefined): 'default' | 'secondary' | 'outline' | 'destructive' {
  if (!state) return 'outline'
  if (state === 'COMPLETED') return 'default'
  if (state === 'FAILED') return 'destructive'
  if (state === 'CANCELLED') return 'outline'
  return 'secondary'
}

export default function App() {
  const [repoUrl, setRepoUrl] = useState('https://github.com/org/repo')
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [activeSnapshot, setActiveSnapshot] = useState<RunSnapshot | null>(null)
  const [recentRuns, setRecentRuns] = useState<RunSnapshot[]>([])
  const [isStarting, setIsStarting] = useState(false)
  const [streamConnected, setStreamConnected] = useState(false)
  const [lastEventRaw, setLastEventRaw] = useState<string | null>(null)
  const [eventLog, setEventLog] = useState<Array<{ t: string; data: string }>>([])
  const latestTransitionCountRef = useRef<number>(0)

  const refreshRecent = useCallback(async () => {
    try {
      const res = await fetch('/api/analyze-repository?limit=20')
      if (!res.ok) return
      const data = await res.json() as { runs: RunSnapshot[] }
      setRecentRuns(data.runs || [])
    } catch {
      // noop
    }
  }, [])

  useEffect(() => {
    void refreshRecent()
  }, [refreshRecent])

  const { connected: hookConnected, lastRaw: hookLastRaw, eventLog: hookEventLog, close: hookClose } = useSSE(activeRunId ? `/api/analyze-repository/${activeRunId}/stream` : undefined, (parsed) => {
    // incoming snapshot from hook
    applySnapshot(parsed)
  })

  const closeStream = useCallback(() => {
    hookClose()
    setStreamConnected(false)
  }, [hookClose])

  const applySnapshot = useCallback((incoming: RunSnapshot) => {
    const count = incoming.transitions?.length ?? 0
    const current = latestTransitionCountRef.current
    const currentState = activeSnapshot?.state

    if (!shouldApplySnapshot(activeSnapshot, incoming)) return
    if (count < current) return
    if (isTerminalState(currentState)) return

    latestTransitionCountRef.current = count
    setActiveSnapshot(incoming)

    if (isTerminalState(incoming.state)) {
      closeStream()
      void refreshRecent()
      if (incoming.state === 'CANCELLED') {
        setActiveRunId(null)
      }
    }
  }, [activeSnapshot?.state, closeStream, refreshRecent])

  const connectStream = useCallback(() => {
    // no-op: useSSE auto-connects when activeRunId set
    setStreamConnected(true)
  }, [])

  useEffect(() => () => closeStream(), [closeStream])

  useEffect(() => {
    // mirror hook-connected into UI badge and debug panel
    setStreamConnected(Boolean(hookConnected))
    if (hookLastRaw) setLastEventRaw(hookLastRaw)
    if (hookEventLog && hookEventLog.length > 0) setEventLog(hookEventLog as any)
  }, [hookConnected, hookLastRaw, hookEventLog])

  const startAnalysis = useCallback(async () => {
    if (!repoUrl.trim()) return
    setIsStarting(true)
    latestTransitionCountRef.current = 0
    setActiveSnapshot(null)

    try {
      const res = await fetch('/api/analyze-repository', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: repoUrl.trim() }),
      })
      if (!res.ok) throw new Error('start_failed')
      const data = await res.json() as { run_id: string }
      setActiveRunId(data.run_id)
      connectStream()
      void refreshRecent()
    } finally {
      setIsStarting(false)
    }
  }, [repoUrl, connectStream, refreshRecent])

  const cancelAnalysis = useCallback(async () => {
    if (!activeRunId) return
    await fetch(`/api/analyze-repository/${activeRunId}/cancel`, { method: 'POST' })
  }, [activeRunId])

  const scores = activeSnapshot?.result_snapshot?.scores || undefined
  const evidence = activeSnapshot?.result_snapshot?.evidence as Record<string, unknown> | undefined
  const topology = activeSnapshot?.result_snapshot?.topology

  const riskItems = useMemo(() => {
    const items: Array<{ name: string; level: 'high' | 'moderate' | 'low' }> = []
    const regression = scores?.regression_risk
    if (typeof regression === 'number') {
      items.push({ name: 'Regression risk', level: regression > 0.7 ? 'high' : regression > 0.4 ? 'moderate' : 'low' })
    }
    if (!evidence?.prometheus) items.push({ name: 'Missing Prometheus evidence', level: 'high' })
    if (!evidence?.otel) items.push({ name: 'Missing OTEL evidence', level: 'moderate' })
    if ((topology?.edges?.length || 0) === 0) items.push({ name: 'Topology relationships sparse', level: 'moderate' })
    return items
  }, [scores, evidence, topology?.edges?.length])

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border bg-card/80 backdrop-blur">
        <div className="container mx-auto px-6 py-5 flex items-center justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">DevANT Repository Operational Intelligence</h1>
            <p className="text-sm text-muted-foreground">Operationally truthful analysis under incomplete evidence</p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={streamConnected ? 'default' : 'outline'}>
              {streamConnected ? <Wifi className="h-3 w-3 mr-1" /> : <WifiOff className="h-3 w-3 mr-1" />}
              {streamConnected ? 'Live Stream' : 'Stream Reconnecting'}
            </Badge>
            <Badge variant="secondary">
              <Activity className="h-3 w-3 mr-1" />
              Real-time
            </Badge>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-6 py-8 space-y-6">
        <section className="p-4 rounded-xl border border-border bg-card">
          <div className="flex flex-col md:flex-row gap-3">
            <input
              value={repoUrl}
              onChange={(event) => setRepoUrl(event.target.value)}
              placeholder="https://github.com/org/repo"
              className="flex-1 h-10 rounded-md bg-background border border-input px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
            />
            <Button onClick={startAnalysis} disabled={isStarting || !repoUrl.trim()}>
              <Search className="h-4 w-4 mr-2" />
              {isStarting ? 'Starting...' : 'Analyze Repository'}
            </Button>
            <Button variant="outline" onClick={cancelAnalysis} disabled={!activeRunId || isTerminalState(activeSnapshot?.state)}>
              <Square className="h-4 w-4 mr-2" />
              Cancel
            </Button>
          </div>

          <div className="mt-4 flex flex-wrap gap-2 text-xs">
            <Badge variant={stateVariant(activeSnapshot?.state)}>
              State: {activeSnapshot?.state || 'IDLE'}
            </Badge>
            {activeRunId && <Badge variant="outline">Run: {activeRunId.slice(0, 8)}...</Badge>}
            <Badge variant="outline">Partial render: enabled</Badge>
            <Badge variant="outline">Uncertainty-first UI</Badge>
          </div>
        </section>

        <RepositoryPipeline snapshot={activeSnapshot} />

        <PipelineTimeline snapshot={activeSnapshot} />

        <section className="rounded-xl border border-border bg-card p-4 space-y-3">
          <h2 className="font-semibold">Stream Debug</h2>
            <div className="text-xs text-muted-foreground">Last event type: -</div>
            <div className="text-xs text-muted-foreground">Last raw payload:</div>
          <pre className="max-h-40 overflow-auto text-[11px] p-2 bg-muted/5 rounded">{lastEventRaw || '-'}</pre>
          <div className="text-xs font-medium">Recent events</div>
          <div className="max-h-40 overflow-auto text-xs">
            {eventLog.map((e, i) => (
              <div key={i} className="py-1 border-b border-border">[{e.t}] {e.data.slice(0, 200)}{e.data.length > 200 ? '…' : ''}</div>
            ))}
          </div>
        </section>

        <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <h2 className="font-semibold">Repository Overview</h2>
            <div className="text-sm text-muted-foreground">Repository: {activeSnapshot?.repo_url || '-'}</div>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <Metric label="Services detected" value={(topology?.services?.length ?? 0).toString()} />
              <Metric label="Workflows detected" value={String((evidence?.workflows as unknown[] | undefined)?.length ?? 0)} />
              <Metric label="Kubernetes manifests" value={String((evidence?.kubernetes_manifests as unknown[] | undefined)?.length ?? 0)} />
              <Metric label="Deployment systems" value={[((evidence?.dockerfiles as unknown[] | undefined)?.length ?? 0) > 0 ? 'Docker' : null, ((evidence?.kubernetes_manifests as unknown[] | undefined)?.length ?? 0) > 0 ? 'K8s' : null, ((evidence?.helm_charts as unknown[] | undefined)?.length ?? 0) > 0 ? 'Helm' : null].filter(Boolean).join(', ') || 'Unknown'} />
            </div>
          </div>

          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <h2 className="font-semibold">Operational Readiness</h2>
            <ScoreRow name="Production readiness" score={scores?.production_readiness} />
            <ScoreRow name="Deployment maturity" score={scores?.deployment_maturity} />
            <ScoreRow name="Observability readiness" score={scores?.observability_readiness} />
            <ScoreRow name="Rollback safety" score={scores?.rollback_safety} />
            <ScoreRow name="Topology resilience" score={scores?.topology_resilience} />
            <p className="text-xs text-muted-foreground">Confidence and uncertainty visible; sparse evidence lowers trust.</p>
          </div>
        </section>

        <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <h2 className="font-semibold">Evidence Intelligence</h2>
            <EvidenceRow name="Prometheus" present={Boolean(evidence?.prometheus)} />
            <EvidenceRow name="OTEL" present={Boolean(evidence?.otel)} />
            <EvidenceRow name="Terraform" present={((evidence?.terraform as unknown[] | undefined)?.length ?? 0) > 0} />
            <EvidenceRow name="Rollback hints" present={((evidence?.helm_charts as unknown[] | undefined)?.length ?? 0) > 0} />
            <div className="text-xs text-muted-foreground">Missing evidence shown explicitly; no certainty inflation.</div>
          </div>

          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            <h2 className="font-semibold flex items-center gap-2"><Network className="h-4 w-4" />Topology Intelligence</h2>
            <div className="text-sm">Nodes: {topology?.services?.length ?? 0} • Edges: {topology?.edges?.length ?? 0}</div>
            <div className="max-h-52 overflow-auto rounded-md border border-border p-2 text-xs">
              {(topology?.edges?.length ?? 0) === 0 ? (
                <div className="text-muted-foreground">No evidence-supported relationships yet.</div>
              ) : (
                topology?.edges?.map((edge, index) => (
                  <div key={`${edge.from}-${edge.to}-${index}`} className="py-1">{edge.from} → {edge.to}</div>
                ))
              )}
            </div>
            <div className="text-xs text-muted-foreground">Only evidence-supported relationships rendered.</div>
          </div>
        </section>

        <section className="rounded-xl border border-border bg-card p-4 space-y-3">
          <h2 className="font-semibold flex items-center gap-2"><AlertTriangle className="h-4 w-4" />Operational Risks</h2>
          <div className="grid md:grid-cols-2 gap-2">
            {riskItems.length === 0 && <div className="text-sm text-muted-foreground">No strong risk signal yet.</div>}
            {riskItems.map((risk, index) => (
              <div key={`${risk.name}-${index}`} className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm">
                <span>{risk.name}</span>
                <Badge variant={risk.level === 'high' ? 'destructive' : risk.level === 'moderate' ? 'secondary' : 'outline'}>{risk.level}</Badge>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="font-semibold mb-3">Recent Analyses</h2>
          <div className="space-y-2 max-h-64 overflow-auto">
            {recentRuns.length === 0 && <div className="text-sm text-muted-foreground">No runs yet.</div>}
            {recentRuns.map((run) => (
              <button
                key={run.run_id}
                className="w-full text-left rounded-md border border-border px-3 py-2 hover:bg-muted/30 transition-colors"
                onClick={() => {
                  setActiveRunId(run.run_id)
                  latestTransitionCountRef.current = run.transitions?.length ?? 0
                  setActiveSnapshot(run)
                  if (!isTerminalState(run.state)) {
                    connectStream()
                  }
                }}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="text-sm truncate">{run.repo_url}</div>
                  <Badge variant={stateVariant(run.state)}>{run.state}</Badge>
                </div>
              </button>
            ))}
          </div>
        </section>
      </main>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-sm font-medium">{value}</div>
    </div>
  )
}

function ScoreRow({ name, score }: { name: string; score: number | undefined }) {
  const display = score === undefined ? 'unknown' : `${Math.round(score * 100)}%`
  return (
    <div className="flex items-center justify-between text-sm">
      <span>{name}</span>
      <div className="flex items-center gap-2">
        <Badge variant={scoreBadgeVariant(score)}>{display}</Badge>
        <span className="text-xs text-muted-foreground">confidence: {score === undefined ? 'low' : score >= 0.7 ? 'high' : score >= 0.45 ? 'moderate' : 'low'}</span>
      </div>
    </div>
  )
}

function EvidenceRow({ name, present }: { name: string; present: boolean }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span>{name}</span>
      <Badge variant={present ? 'default' : 'outline'}>{present ? 'found' : 'missing'}</Badge>
    </div>
  )
}
