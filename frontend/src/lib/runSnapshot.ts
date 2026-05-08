export type JobState =
  | 'PENDING'
  | 'INITIALIZING'
  | 'INGESTING'
  | 'ANALYZING'
  | 'SCORING'
  | 'FINALIZING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'

export interface MinimalSnapshot {
  state: JobState
  transitions?: Array<unknown>
}

export function isTerminalState(state: JobState | undefined): boolean {
  return state === 'COMPLETED' || state === 'FAILED' || state === 'CANCELLED'
}

export function shouldApplySnapshot(current: MinimalSnapshot | null, incoming: MinimalSnapshot): boolean {
  const currentCount = current?.transitions?.length ?? 0
  const incomingCount = incoming.transitions?.length ?? 0

  if (isTerminalState(current?.state)) return false
  if (incomingCount < currentCount) return false
  return true
}
