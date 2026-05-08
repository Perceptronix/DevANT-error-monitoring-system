import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, AlertTriangle, ChevronRight, Network, Search, Square, Wifi, WifiOff } from 'lucide-react'
import RepositoryPipeline from '@/components/RepositoryPipeline'
import PipelineTimeline from '@/components/PipelineTimeline'
import useSSE from '@/hooks/useSSE'
import { Button } from '@/components/ui/button'
import { StatusDot, StatusColor } from '@/components/ui/StatusDot'
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

function stateStatusColor(state: JobState | undefined): StatusColor {
  if (!state) return 'gray'
  if (state === 'COMPLETED') return 'green'
  if (state === 'FAILED') return 'red'
  if (state === 'CANCELLED') return 'gray'
  return 'blue'
}

export default function App() {
  const [repoUrl, setRepoUrl] = useState('https://github.com/org/repo')
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [activeSnapshot, setActiveSnapshot] = useState<RunSnapshot | null>(null)
  const [recentRuns, setRecentRuns] = useState<RunSnapshot[]>([])
  const [isStarting, setIsStarting] = useState(false)
  const [streamConnected, setStreamConnected] = useState(false)
  const [backendConnection, setBackendConnection] = useState<'unknown' | 'checking' | 'connected' | 'disconnected'>('unknown')
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

  const checkBackendConnection = useCallback(async () => {
    setBackendConnection('checking')
    try {
      const response = await fetch('/api/config')
      if (!response.ok) {
        setBackendConnection('disconnected')
        return
      }
      const payload = await response.json().catch(() => null)
      if (payload?.airweave_configured !== undefined) {
        setBackendConnection('connected')
      } else {
        setBackendConnection('disconnected')
      }
    } catch {
      setBackendConnection('disconnected')
    }
  }, [])

  useEffect(() => {
    void refreshRecent()
  }, [refreshRecent])

  useEffect(() => {
    void checkBackendConnection()
  }, [checkBackendConnection])

  const applySnapshot = useCallback((incoming: RunSnapshot) => {
    setActiveSnapshot((prev) => {
      const count = incoming.transitions?.length ?? 0
      const current = latestTransitionCountRef.current
      const currentState = prev?.state

      if (!shouldApplySnapshot(prev, incoming)) return prev
      if (count < current) return prev
      if (isTerminalState(currentState)) return prev

      latestTransitionCountRef.current = count
      return incoming
    })
  }, [])

  const { connected: hookConnected, lastRaw: hookLastRaw, eventLog: hookEventLog, close: hookClose } = useSSE(activeRunId ? `/api/analyze-repository/${activeRunId}/stream` : undefined, applySnapshot)

  const closeStream = useCallback(() => {
    hookClose()
    setStreamConnected(false)
  }, [hookClose])

  const connectStream = useCallback(() => {
    // no-op: useSSE auto-connects when activeRunId set
    setStreamConnected(true)
  }, [])

  useEffect(() => () => closeStream(), [closeStream])

  // Handle terminal state separately to avoid circular dependencies
  useEffect(() => {
    if (activeSnapshot && isTerminalState(activeSnapshot.state)) {
      closeStream()
      void refreshRecent()
      if (activeSnapshot.state === 'CANCELLED') {
        setActiveRunId(null)
      }
    }
  }, [activeSnapshot?.state, closeStream, refreshRecent])

  useEffect(() => {
    // mirror hook-connected into UI badge and debug panel
    setStreamConnected(Boolean(hookConnected))
  }, [hookConnected])

  useEffect(() => {
    if (hookLastRaw) setLastEventRaw(hookLastRaw)
  }, [hookLastRaw])

  useEffect(() => {
    if (hookEventLog && hookEventLog.length > 0) setEventLog(hookEventLog as any)
  }, [hookEventLog])

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
    <div className="min-h-screen bg-background text-foreground font-sans">
      <header className="border-b border-border bg-card/50 backdrop-blur sticky top-0 z-10">
        <div className="container mx-auto px-6 py-3 flex items-center justify-between gap-4">
          <div>
            <h1 className="text-sm font-medium tracking-tight">DevANT AI Operational Assistant</h1>
          </div>
          <div className="flex items-center gap-4 text-xs">
            <div className="flex items-center gap-1.5">
              <StatusDot status={backendConnection === 'connected' ? 'green' : backendConnection === 'disconnected' ? 'red' : 'gray'} />
              <span className="text-muted-foreground cursor-pointer hover:text-foreground" onClick={checkBackendConnection}>
                {backendConnection === 'checking' ? 'Checking Backend...' : backendConnection === 'connected' ? 'Backend Ready' : 'Backend Disconnected'}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <StatusDot status={streamConnected ? 'green' : 'gray'} animate={streamConnected} />
              <span className="text-muted-foreground">{streamConnected ? 'Live Stream' : 'Stream Reconnecting'}</span>
            </div>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-6 py-8 grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left Primary Column */}
        <div className="lg:col-span-2 space-y-6">
          <section className="flex flex-col md:flex-row gap-3">
            <input
              value={repoUrl}
              onChange={(event) => setRepoUrl(event.target.value)}
              placeholder="https://github.com/org/repo"
              className="flex-1 h-10 rounded-md bg-card border border-border px-3 text-sm outline-none focus:border-primary transition-colors"
            />
            <Button onClick={startAnalysis} disabled={isStarting || !repoUrl.trim()} className="bg-primary text-primary-foreground hover:bg-primary/90">
              <Search className="h-4 w-4 mr-2" />
              {isStarting ? 'Starting...' : 'Analyze Repository'}
            </Button>
            <Button variant="outline" onClick={cancelAnalysis} disabled={!activeRunId || isTerminalState(activeSnapshot?.state)} className="border-border hover:bg-muted">
              <Square className="h-4 w-4 mr-2" />
              Cancel
            </Button>
          </section>

          <div className="flex items-center gap-3 text-xs text-muted-foreground border-b border-border pb-4">
            <div className="flex items-center gap-1.5">
              <StatusDot status={stateStatusColor(activeSnapshot?.state)} animate={activeSnapshot?.state === 'ANALYZING'} />
              <span>{activeSnapshot?.state || 'IDLE'}</span>
            </div>
            {activeRunId && <span>• Run: {activeRunId.slice(0, 8)}</span>}
          </div>

          <RepositoryPipeline snapshot={activeSnapshot} />

          <section className="space-y-3">
            <h2 className="text-sm font-medium">Current Risks</h2>
            <div className="grid md:grid-cols-2 gap-2">
              {riskItems.length === 0 && <div className="text-xs text-muted-foreground p-3 rounded-md border border-border">No strong risk signal yet.</div>}
              {riskItems.map((risk, index) => (
                <div key={`${risk.name}-${index}`} className="flex items-center gap-3 rounded-md border border-border px-3 py-2 text-sm bg-card">
                  <StatusDot status={risk.level === 'high' ? 'red' : risk.level === 'moderate' ? 'yellow' : 'gray'} />
                  <span>{risk.name}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="space-y-3">
            <h2 className="text-sm font-medium">What We Found</h2>
            <EvidenceSummary evidence={evidence} />
          </section>

          <section className="space-y-3">
            <h2 className="text-sm font-medium flex items-center gap-2">Service Map</h2>
            <div className="rounded-md border border-border bg-card p-4 space-y-3">
              <div className="text-sm text-muted-foreground">Services: {topology?.services?.length ?? 0} • Connections: {topology?.edges?.length ?? 0}</div>
              <div className="max-h-52 overflow-auto text-sm space-y-1">
                {(topology?.edges?.length ?? 0) === 0 ? (
                  <div className="text-muted-foreground text-xs">No evidence-supported relationships yet.</div>
                ) : (
                  topology?.edges?.map((edge, index) => (
                    <div key={`${edge.from}-${edge.to}-${index}`} className="py-1 px-2 rounded hover:bg-muted/30 transition-colors">
                      <span className="text-muted-foreground">{edge.from}</span> <span className="mx-2 text-xs">→</span> <span>{edge.to}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </section>

          <section className="space-y-3">
            <h2 className="text-sm font-medium mb-3">Recent Analyses</h2>
            <div className="space-y-2 max-h-64 overflow-auto">
              {recentRuns.length === 0 && <div className="text-xs text-muted-foreground p-3 border border-border rounded-md">No runs yet.</div>}
              {recentRuns.map((run) => (
                <button
                  key={run.run_id}
                  className="w-full text-left flex items-center justify-between rounded-md border border-border px-3 py-2 bg-card hover:bg-muted/50 transition-colors"
                  onClick={() => {
                    setActiveRunId(run.run_id)
                    latestTransitionCountRef.current = run.transitions?.length ?? 0
                    setActiveSnapshot(run)
                    if (!isTerminalState(run.state)) {
                      connectStream()
                    }
                  }}
                >
                  <div className="text-sm truncate mr-4">{run.repo_url}</div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">{run.state}</span>
                    <StatusDot status={stateStatusColor(run.state)} />
                  </div>
                </button>
              ))}
            </div>
          </section>
        </div>

        {/* Right Sidebar */}
        <div className="space-y-8">
          <section className="space-y-3">
            <h2 className="text-sm font-medium">Status Guide</h2>
            <div className="rounded-md border border-border bg-card p-4 space-y-3 text-xs">
              <div className="flex items-center gap-2"><StatusDot status="green" /> <span>Healthy / Ready</span></div>
              <div className="flex items-center gap-2"><StatusDot status="yellow" /> <span>Needs Attention</span></div>
              <div className="flex items-center gap-2"><StatusDot status="red" /> <span>Problem / Risk</span></div>
              <div className="flex items-center gap-2"><StatusDot status="blue" animate /> <span>Analyzing</span></div>
              <div className="flex items-center gap-2"><StatusDot status="gray" /> <span>Unknown / Missing</span></div>
            </div>
          </section>

          <section className="space-y-3">
            <SystemConfidencePanel scores={scores} evidence={evidence} />
          </section>

          <section className="space-y-3">
            <h2 className="text-sm font-medium">Repository Overview</h2>
            <div className="rounded-md border border-border bg-card p-4 space-y-3">
              <div className="text-xs text-muted-foreground break-all">{activeSnapshot?.repo_url || '-'}</div>
              <div className="space-y-2">
                <Metric label="Services detected" value={(topology?.services?.length ?? 0).toString()} />
                <Metric label="Workflows detected" value={String((evidence?.workflows as unknown[] | undefined)?.length ?? 0)} />
                <Metric label="Kubernetes manifests" value={String((evidence?.kubernetes_manifests as unknown[] | undefined)?.length ?? 0)} />
                <Metric label="Deployment systems" value={[((evidence?.dockerfiles as unknown[] | undefined)?.length ?? 0) > 0 ? 'Docker' : null, ((evidence?.kubernetes_manifests as unknown[] | undefined)?.length ?? 0) > 0 ? 'K8s' : null, ((evidence?.helm_charts as unknown[] | undefined)?.length ?? 0) > 0 ? 'Helm' : null].filter(Boolean).join(', ') || 'Unknown'} />
              </div>
            </div>
          </section>

          <section className="space-y-3">
            <h2 className="text-sm font-medium">Health Breakdown</h2>
            <div className="rounded-md border border-border bg-card p-4 space-y-3">
              <ScoreRow name="Production Readiness" score={scores?.production_readiness} />
              <ScoreRow name="Deployment Setup" score={scores?.deployment_maturity} />
              <ScoreRow name="Monitoring Check" score={scores?.observability_readiness} />
              <ScoreRow name="Rollback Safety" score={scores?.rollback_safety} />
              <ScoreRow name="Service Connections" score={scores?.topology_resilience} />
            </div>
          </section>

          <section className="space-y-3">
            <h2 className="text-sm font-medium">Run Timeline</h2>
            <div className="rounded-md border border-border bg-card p-4">
              <PipelineTimeline snapshot={activeSnapshot} />
            </div>
          </section>
        </div>

      </main>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-1 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  )
}

function ScoreRow({ name, score }: { name: string; score: number | undefined }) {
  const display = score === undefined ? '-' : `${Math.round(score * 100)}%`
  const status: StatusColor = score === undefined ? 'gray' : score >= 0.7 ? 'green' : score >= 0.45 ? 'yellow' : 'red'
  return (
    <div className="flex items-center justify-between text-sm py-1 border-b border-border/50 last:border-0">
      <span>{name}</span>
      <div className="flex items-center gap-3">
        <StatusDot status={status} />
        <span className="tabular-nums w-8 text-right font-medium">{display}</span>
      </div>
    </div>
  )
}

function EvidenceRow({ name, present }: { name: string; present: boolean }) {
  return (
    <div className="flex items-center justify-between text-sm py-1.5">
      <span>{name}</span>
      <div className="flex items-center gap-2">
        <StatusDot status={present ? 'green' : 'gray'} />
        <span className="text-xs text-muted-foreground">{present ? 'found' : 'missing'}</span>
      </div>
    </div>
  )
}

function EvidenceSummary({ evidence }: { evidence: Record<string, unknown> | undefined }) {
  const groups = [
    {
      name: 'Project Files',
      items: [
        { name: 'Workflows', present: ((evidence?.workflows as unknown[] | undefined)?.length ?? 0) > 0 },
        { name: 'Dockerfiles', present: ((evidence?.dockerfiles as unknown[] | undefined)?.length ?? 0) > 0 },
        { name: 'Kubernetes', present: ((evidence?.kubernetes_manifests as unknown[] | undefined)?.length ?? 0) > 0 },
        { name: 'Terraform', present: ((evidence?.terraform as unknown[] | undefined)?.length ?? 0) > 0 },
      ],
    },
    {
      name: 'Monitoring & Tracing',
      items: [
        { name: 'Prometheus', present: Boolean(evidence?.prometheus) },
        { name: 'OTEL', present: Boolean(evidence?.otel) },
      ],
    },
    {
      name: 'Risk Signals',
      items: [
        { name: 'Rollback hints', present: ((evidence?.helm_charts as unknown[] | undefined)?.length ?? 0) > 0 },
        { name: 'Regression evidence', present: Boolean((evidence as any)?.regression || (evidence as any)?.regression_analysis) },
      ],
    },
    {
      name: 'Past Activity',
      items: [
        { name: 'Memory accessible', present: Boolean((evidence as any)?.temporal_memory) },
        { name: 'Recurring patterns', present: Boolean((evidence as any)?.temporal_memory?.recurring_patterns) },
        { name: 'Operational drift', present: Boolean((evidence as any)?.temporal_memory?.operational_drift) },
      ],
    },
  ]

  const flat = groups.flatMap((g) => g.items)
  const present = flat.filter((i) => i.present).length
  const total = flat.length

  return (
    <div className="space-y-2">
      <div className="rounded-md border border-border p-3 text-sm">
        <div className="font-medium">Evidence summary</div>
        <div className="text-xs text-muted-foreground mt-1">
          {present}/{total} evidence signals available. Expand layers for details.
        </div>
      </div>

      {groups.map((group) => {
        const groupPresent = group.items.filter((i) => i.present).length
        return (
          <details key={group.name} className="rounded-md border border-border p-3 bg-card group">
            <summary className="cursor-pointer list-none flex items-center justify-between text-sm">
              <span className="font-medium flex items-center gap-2">
                <ChevronRight className="h-4 w-4 text-muted-foreground group-open:rotate-90 transition-transform" />
                {group.name}
              </span>
              <span className="text-xs text-muted-foreground">{groupPresent}/{group.items.length} found</span>
            </summary>
            <div className="mt-3 pl-6 space-y-1">
              {group.items.map((item) => (
                <EvidenceRow key={`${group.name}-${item.name}`} name={item.name} present={item.present} />
              ))}
            </div>
          </details>
        )
      })}
    </div>
  )
}

function SystemConfidencePanel({
  scores,
  evidence,
}: {
  scores: Record<string, number> | undefined
  evidence: Record<string, unknown> | undefined
}) {
  const candidates = [
    ['Production readiness', scores?.production_readiness],
    ['Deployment maturity', scores?.deployment_maturity],
    ['Observability readiness', scores?.observability_readiness],
    ['Rollback safety', scores?.rollback_safety],
    ['Topology resilience', scores?.topology_resilience],
  ].filter(([, value]) => typeof value === 'number') as Array<[string, number]>

  const consensus = candidates.length > 0 ? candidates.reduce((sum, [, value]) => sum + value, 0) / candidates.length : 0

  const requiredSignals = [
    Boolean(evidence?.prometheus),
    Boolean(evidence?.otel),
    ((evidence?.kubernetes_manifests as unknown[] | undefined)?.length ?? 0) > 0,
    ((evidence?.workflows as unknown[] | undefined)?.length ?? 0) > 0,
    Boolean((evidence as any)?.temporal_memory),
  ]
  const coverage = requiredSignals.filter(Boolean).length / requiredSignals.length
  const uncertainty = Math.max(0, 1 - (consensus * 0.7 + coverage * 0.3))

  let dominantSignal = 'No dominant signal yet'
  if (candidates.length > 0) {
    dominantSignal = candidates.reduce((best, current) => (current[1] > best[1] ? current : best), candidates[0])[0]
  }

  return (
    <div className="rounded-md border border-border bg-card p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium">System Confidence</h2>
        <StatusDot status={uncertainty > 0.5 ? 'yellow' : 'green'} />
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>Confidence Level</span>
          <span>{Math.round(consensus * 100)}%</span>
        </div>
        <div className="h-1.5 rounded-full bg-muted overflow-hidden">
          <div className="h-full bg-primary transition-all" style={{ width: `${Math.round(consensus * 100)}%` }} />
        </div>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>Uncertainty</span>
          <span>{Math.round(uncertainty * 100)}%</span>
        </div>
        <div className="h-1.5 rounded-full bg-muted overflow-hidden">
          <div className="h-full bg-yellow-500/50 transition-all" style={{ width: `${Math.round(uncertainty * 100)}%` }} />
        </div>
      </div>

      <div className="pt-2 border-t border-border/50">
        <p className="text-xs text-muted-foreground">
          {uncertainty > 0.5 ? 'Confidence is low due to missing monitoring or architecture signals.' : 'System has sufficient evidence for a reliable assessment.'}
        </p>
      </div>
    </div>
  )
}
