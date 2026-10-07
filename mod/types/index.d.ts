export type VaultNote = { title: string; file: string; uri: string }
export type VaultSession = { date: string; title: string; uri: string }
export type VaultDraft = { sid: string; state: string; note: string; path: string }
export type VaultHook = { name: string; last: string | null }
export type VaultSnapshot = {
  vault: string
  helpers: string
  inbox: VaultNote[]
  hub: string | null
  hubSessions: VaultSession[]
  drafts: VaultDraft[]
  hooks: VaultHook[]
  dashboardStale: boolean
}

export type TriageItem = { file: string; why: string }
export type TriageResult = {
  ok: boolean
  err: string
  noKey: boolean
  proposed: TriageItem[]
  review: TriageItem[]
  filed: TriageItem[]
}
export type TriageAsk = {
  kind: 'ask' | 'apply' | 'save'
  status: 'running' | 'done' | 'failed'
  text: string
  hub: string | null
}
export type TriageState = {
  phase: 'idle' | 'running' | 'ready' | 'filing' | 'done' | 'error'
  proposed: TriageItem[]
  review: TriageItem[]
  filed: TriageItem[]
  note: string
  asks: Record<string, TriageAsk>
}

declare module 'claude-code' {
  interface PluginState {
    'second-brain-mod': { snap: VaultSnapshot | null; isHidden: boolean; triage: TriageState }
  }
}
