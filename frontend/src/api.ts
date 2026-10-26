// Thin typed client for the HorseIQ FastAPI backend (proxied at /api by Vite in development).

export type World = 'REAL' | 'DEMO'
export type InterventionType = 'start' | 'blocked' | 'late' | 'traffic'
export type Phase = 'early' | 'final_turn' | 'final_straight'

export interface FormSettings {
  mode: 'days' | 'races'
  days: number
  races: number
  track_scope: 'same' | 'any'
  surface_scope: 'same' | 'any'
  distance_tolerance_m: number | null
}

export const DEFAULT_SETTINGS: FormSettings = {
  mode: 'days',
  days: 400,
  races: 3,
  track_scope: 'same',
  surface_scope: 'same',
  distance_tolerance_m: 200,
}

export interface RaceSummary {
  id: number
  race_no: number
  post_time: string | null
  distance_m: number | null
  surface: string | null
  going: string | null
  race_class: string | null
  has_results: boolean
  data_status: string
  runners: number
}

export interface Meeting {
  track_code: string
  track_name: string
  races: RaceSummary[]
}

export interface Component {
  score: number | null
  status: string
  note: string
}

export interface RunnerInfo {
  horse_id: number
  program_no: number
  name: string
  gate: number | null
  jockey: string | null
  weight_kg: number | null
  jockey_changed: boolean
  form: {
    score: number | null
    runs_used: number
    status: string
    confidence: number
    components: Record<string, Component>
    profile: Record<string, unknown> & { status: Record<string, string> }
  }
}

export interface RaceDetail {
  id: number
  date: string
  track_code: string
  track_name: string
  race_no: number
  post_time: string | null
  distance_m: number
  surface: string | null
  going: string | null
  race_class: string | null
  has_results: boolean
  data_status: string
  source_system: string
  geometry: { home_straight_m: number; turn_radius_m: number; assumed: boolean }
  speed_model: { fitted: boolean; n_fit: number }
  runners: RunnerInfo[]
  scratched: { program_no: number; name: string }[]
}

export interface OrderRow {
  pos: number
  horse_id: number
  program_no: number
  name: string
  time_s: number | null
  gap_prev_s?: number
  gap_win_s?: number
  gap_prev_len?: number
  gap_win_len?: number
  gap_prev_text?: string
  energy_left: number
  ground_m: number
}

export interface SimEvent {
  t: number
  horse_id: number
  type: string
  text: string
  intervention?: boolean
}

export interface SimRun {
  seed: number
  distance_m: number
  order: OrderRow[]
  frames: { t: number; h: [number, number, number, number][] }[]
  events: SimEvent[]
  dt: number
}

export interface ActualRow {
  horse_id: number
  finish_pos: number | null
  finish_time_s: number | null
  margin_text: string | null
  status: string
  program_no: number | null
  name: string
}

export interface SimResponse {
  race: RaceDetail
  seed: number
  normal: SimRun
  intervention?: SimRun
  comparison?: { horse_id: number; program_no: number; name: string; before: number; after: number; time_delta_s: number }[]
  actual: ActualRow[] | null
}

export interface Meta {
  races: Record<string, number>
  horses: Record<string, number>
  sectional_rows: number
  tjk_api_configured: boolean
  accurace_configured: boolean
  engine: string
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* not JSON */
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json() as Promise<T>
}

export const api = {
  meta: () => req<Meta>('/meta'),
  dates: (world: World) => req<string[]>(`/dates?world=${world}`),
  meetings: (world: World, day?: string) =>
    req<{ date: string | null; meetings: Meeting[] }>(`/meetings?world=${world}${day ? `&day=${day}` : ''}`),
  race: (id: number) => req<RaceDetail>(`/races/${id}`),
  simulate: (
    id: number,
    body: { settings: FormSettings; seed?: number; intervention?: { horse_id: number; type: InterventionType; phase?: Phase } },
  ) => req<SimResponse>(`/races/${id}/simulate`, { method: 'POST', body: JSON.stringify(body) }),
}
