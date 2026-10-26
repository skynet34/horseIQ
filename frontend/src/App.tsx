import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  api, DEFAULT_SETTINGS,
  type FormSettings, type InterventionType, type Meeting, type Meta, type Phase, type RaceDetail, type SimResponse, type World,
} from './api'
import RaceTrack, { colorFor } from './components/RaceTrack'
import { ActualTable, Podium, ResultsTable } from './components/Results'

const SPEEDS = [1, 2, 3, 5, 10]
const SURFACE_TR: Record<string, string> = { TURF: 'Çim', DIRT: 'Kum', SYNTHETIC: 'Sentetik' }
const IV_LABEL: Record<InterventionType, string> = {
  start: 'Startta kaldı',
  blocked: 'Önü kapandı',
  late: 'Sprinte geç başladı',
  traffic: 'Trafiğe takıldı',
}
const PHASE_LABEL: Record<Phase, string> = { early: 'Başlarda', final_turn: 'Son virajda', final_straight: 'Son düzlükte' }
const STATUS_TR: Record<string, string> = { REAL: 'gerçek', ESTIMATED: 'tahmini', NO_DATA: 'veri yok', DEMO: 'demo' }

export default function App() {
  const [world, setWorld] = useState<World>('REAL')
  const [meta, setMeta] = useState<Meta | null>(null)
  const [dates, setDates] = useState<string[]>([])
  const [day, setDay] = useState<string | undefined>()
  const [meetings, setMeetings] = useState<Meeting[]>([])
  const [trackCode, setTrackCode] = useState<string>()
  const [raceId, setRaceId] = useState<number>()
  const [race, setRace] = useState<RaceDetail | null>(null)
  const [settings, setSettings] = useState<FormSettings>(DEFAULT_SETTINGS)
  const [speed, setSpeed] = useState(3)
  const [sim, setSim] = useState<SimResponse | null>(null)
  const [view, setView] = useState<'normal' | 'intervention'>('normal')
  const [playKey, setPlayKey] = useState(0)
  const [finished, setFinished] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ivHorse, setIvHorse] = useState<number>()
  const [ivType, setIvType] = useState<InterventionType>('blocked')
  const [ivPhase, setIvPhase] = useState<Phase>('final_straight')
  const [showSettings, setShowSettings] = useState(false)
  const [showActual, setShowActual] = useState(false)

  useEffect(() => {
    api.meta().then(setMeta).catch((e) => setError(String(e.message ?? e)))
  }, [])

  // dates + meetings for the selected data world
  useEffect(() => {
    setError(null)
    api.dates(world).then(setDates).catch(() => setDates([]))
    api
      .meetings(world, day)
      .then((m) => {
        setMeetings(m.meetings)
        if (!day && m.date) setDay(m.date)
        const first = m.meetings[0]
        setTrackCode((tc) => (m.meetings.some((x) => x.track_code === tc) ? tc : first?.track_code))
      })
      .catch((e) => setError(String(e.message ?? e)))
  }, [world, day])

  const meeting = meetings.find((m) => m.track_code === trackCode)
  useEffect(() => {
    if (meeting && !meeting.races.some((r) => r.id === raceId)) setRaceId(meeting.races[0]?.id)
    if (!meeting) setRaceId(undefined)
  }, [meeting, raceId])

  useEffect(() => {
    setSim(null)
    setFinished(false)
    setShowActual(false)
    if (raceId == null) {
      setRace(null)
      return
    }
    api
      .race(raceId)
      .then((r) => {
        setRace(r)
        setIvHorse(r.runners[0]?.horse_id)
      })
      .catch((e) => setError(String(e.message ?? e)))
  }, [raceId])

  const run = useCallback(
    async (withIntervention: boolean) => {
      if (!raceId) return
      setBusy(true)
      setError(null)
      try {
        const res = await api.simulate(raceId, {
          settings,
          seed: withIntervention && sim ? sim.seed : undefined, // same luck for a fair comparison
          intervention: withIntervention && ivHorse ? { horse_id: ivHorse, type: ivType, phase: ivType === 'start' ? 'early' : ivPhase } : undefined,
        })
        setSim(res)
        setRace(res.race)
        setView(withIntervention ? 'intervention' : 'normal')
        setFinished(false)
        setPlayKey((k) => k + 1)
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setBusy(false)
      }
    },
    [raceId, settings, sim, ivHorse, ivType, ivPhase],
  )

  const shown = sim ? (view === 'intervention' && sim.intervention ? sim.intervention : sim.normal) : null
  const coverage = useMemo(() => {
    if (!race) return null
    const withData = race.runners.filter((r) => r.form.status !== 'NO_DATA').length
    return { withData, total: race.runners.length }
  }, [race])
  const realCount = meta ? Object.entries(meta.races).filter(([k]) => k !== 'DEMO').reduce((a, [, n]) => a + n, 0) : 0

  const updateSettings = (patch: Partial<FormSettings>) => {
    setSettings((s) => ({ ...s, ...patch }))
    setSim(null)
    setFinished(false)
  }

  return (
    <main>
      <header className="head">
        <div>
          <div className="brand">
            Horse<span>IQ</span> <small>v0.4</small>
          </div>
          <div className="muted">Geçmiş formla sanal yarış · atlar birbirini etkiler</div>
        </div>
        <div className="world-toggle" role="group" aria-label="Veri kaynağı">
          <button className={world === 'REAL' ? 'on' : ''} onClick={() => { setWorld('REAL'); setDay(undefined) }}>Gerçek veri</button>
          <button className={world === 'DEMO' ? 'on demo' : ''} onClick={() => { setWorld('DEMO'); setDay(undefined) }}>Demo</button>
        </div>
      </header>

      {world === 'DEMO' && (
        <div className="banner demo">
          <strong>DEMO modu.</strong> At isimleri, yarışlar ve sonuçlar tamamen sentetiktir (DEMO ile başlayan isimler). Gerçek tahmin değildir.
        </div>
      )}
      {world === 'REAL' && meta && realCount === 0 && (
        <div className="banner warn">
          <strong>Henüz gerçek yarış verisi yok.</strong> TJK verisi lisanslı erişim (authKey) veya elle kaydedilen sayfalarla içe aktarılabilir — ayrıntılar
          <code> docs/DATA_ACCESS.md</code>. Uygulamayı denemek için <button className="link" onClick={() => setWorld('DEMO')}>Demo</button> moduna geçin.
        </div>
      )}
      {error && <div className="banner err">{error}</div>}

      {/* 1. Choose the race */}
      <section className="panel">
        <div className="row between">
          <h2>{day === new Date().toISOString().slice(0, 10) ? 'Bugünün Yarışları' : 'Yarışlar'}</h2>
          {dates.length > 0 && (
            <select value={day} onChange={(e) => setDay(e.target.value)} aria-label="Tarih">
              {dates.map((d) => (
                <option key={d} value={d}>{new Date(d + 'T00:00').toLocaleDateString('tr-TR', { day: 'numeric', month: 'long', year: 'numeric', weekday: 'short' })}</option>
              ))}
            </select>
          )}
        </div>
        <div className="chips" role="tablist" aria-label="Hipodrom">
          {meetings.map((m) => (
            <button key={m.track_code} className={m.track_code === trackCode ? 'chip on' : 'chip'} onClick={() => setTrackCode(m.track_code)}>
              {m.track_name}
            </button>
          ))}
          {meetings.length === 0 && <span className="muted">Bu tarih için koşu yok.</span>}
        </div>
        {meeting && (
          <div className="chips races" role="tablist" aria-label="Koşu">
            {meeting.races.map((r) => (
              <button key={r.id} className={r.id === raceId ? 'chip race on' : 'chip race'} onClick={() => setRaceId(r.id)}>
                <b>{r.race_no}. Koşu</b>
                <span>{r.post_time ?? ''} · {r.distance_m} m {SURFACE_TR[r.surface ?? ''] ?? ''}</span>
              </button>
            ))}
          </div>
        )}
      </section>

      {race && (
        <>
          {/* 2. Run it */}
          <section className="panel">
            <div className="row between wrap">
              <div>
                <h2>
                  {race.track_name} · {race.race_no}. Koşu
                </h2>
                <div className="muted">
                  {race.distance_m} m · {SURFACE_TR[race.surface ?? ''] ?? '?'}
                  {race.going ? ` · ${race.going}` : ''} {race.race_class ? ` · ${race.race_class}` : ''} · {race.runners.length} at
                  {race.scratched.length > 0 && ` · koşmaz: ${race.scratched.map((s) => s.program_no).join(', ')}`}
                </div>
              </div>
              <span className={`pill ${race.data_status === 'DEMO' ? 'demo' : 'real'}`}>{race.data_status === 'DEMO' ? 'DEMO VERİ' : 'TJK VERİSİ'}</span>
            </div>

            <RaceTrack
              race={race}
              run={shown}
              speed={speed}
              playKey={playKey}
              highlightHorse={view === 'intervention' ? sim?.intervention && ivHorse : undefined}
              onFinished={() => setFinished(true)}
            />

            <div className="row between wrap controls">
              <button className="big" disabled={busy} onClick={() => run(false)}>
                {busy ? 'Hesaplanıyor…' : sim ? '↻ YENİDEN KOŞTUR' : '▶ YARIŞI KOŞTUR'}
              </button>
              <div className="speeds" role="group" aria-label="Animasyon hızı">
                {SPEEDS.map((s) => (
                  <button key={s} className={s === speed ? 'on' : ''} onClick={() => setSpeed(s)}>{s}×</button>
                ))}
                {shown && <button title="Tekrar izle" onClick={() => { setFinished(false); setPlayKey((k) => k + 1) }}>⟲</button>}
              </div>
            </div>
            {coverage && (
              <p className="fine">
                {coverage.withData}/{coverage.total} at için form filtresine uygun geçmiş koşu bulundu.
                {coverage.withData < coverage.total && ' Verisi olmayan atlar sahanın ortanca hızıyla, varsayımsal profille koşar ("veri yok").'}
                {' '}Ara derece verisi olmadığından tempo/finiş profilleri <b>tahminidir</b>.
              </p>
            )}
          </section>

          {/* 3. Results */}
          {sim && shown && finished && (
            <section className="panel">
              <div className="row between wrap">
                <h2>{view === 'intervention' ? 'Müdahaleli sonuç' : 'Sanal sonuç'}</h2>
                {sim.intervention && (
                  <div className="speeds">
                    <button className={view === 'normal' ? 'on' : ''} onClick={() => { setView('normal'); setFinished(false); setPlayKey((k) => k + 1) }}>Normal</button>
                    <button className={view === 'intervention' ? 'on' : ''} onClick={() => { setView('intervention'); setFinished(false); setPlayKey((k) => k + 1) }}>Müdahaleli</button>
                  </div>
                )}
              </div>
              <Podium order={shown.order} />
              <ResultsTable order={shown.order} race={race} />
              {sim.comparison && (
                <>
                  <h3>Normal → Müdahaleli</h3>
                  <ul className="compare">
                    {sim.comparison.map((c) => (
                      <li key={c.horse_id}>
                        <span className="silk sm" style={{ background: colorFor(c.program_no) }}>{c.program_no}</span> {c.name}
                        <span className={c.after < c.before ? 'up' : c.after > c.before ? 'down' : 'same'}>
                          {c.before}. → {c.after}. {c.after < c.before ? '▲' : c.after > c.before ? '▼' : ''}
                        </span>
                        <span className="muted">{c.time_delta_s > 0 ? '+' : ''}{c.time_delta_s.toFixed(2)} sn</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {sim.actual && (
                <>
                  <button className="link" onClick={() => setShowActual((v) => !v)}>{showActual ? 'Resmî sonucu gizle' : 'Bu koşunun resmî sonucunu göster'}</button>
                  {showActual && <ActualTable actual={sim.actual} />}
                </>
              )}
            </section>
          )}

          {/* 4. Optional intervention */}
          {sim && (
            <section className="panel">
              <h2>Müdahale et <span className="muted">(isteğe bağlı)</span></h2>
              <div className="grid3">
                <label>
                  At
                  <select value={ivHorse} onChange={(e) => setIvHorse(Number(e.target.value))}>
                    {race.runners.map((r) => (
                      <option key={r.horse_id} value={r.horse_id}>{r.program_no} · {r.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Olay
                  <select value={ivType} onChange={(e) => setIvType(e.target.value as InterventionType)}>
                    {(Object.keys(IV_LABEL) as InterventionType[]).map((k) => (
                      <option key={k} value={k}>{IV_LABEL[k]}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Ne zaman
                  <select value={ivType === 'start' ? 'early' : ivPhase} disabled={ivType === 'start'} onChange={(e) => setIvPhase(e.target.value as Phase)}>
                    {(Object.keys(PHASE_LABEL) as Phase[]).filter((p) => ivType !== 'late' || p !== 'early').map((k) => (
                      <option key={k} value={k}>{PHASE_LABEL[k]}</option>
                    ))}
                  </select>
                </label>
              </div>
              <button className="big secondary" disabled={busy} onClick={() => run(true)}>Müdahaleyle yeniden koştur</button>
              <p className="fine">Yarış aynı başlangıç şansıyla baştan hesaplanır; diğer atlar da yeni duruma tepki verir.</p>
            </section>
          )}

          {/* Runners & form (kept compact) */}
          <section className="panel">
            <div className="row between">
              <h2>Atlar ve form</h2>
              <button className="link" onClick={() => setShowSettings((v) => !v)}>{showSettings ? 'Form ayarlarını kapat' : 'Form ayarları'}</button>
            </div>
            {showSettings && <SettingsPanel settings={settings} onChange={updateSettings} />}
            <div className="table-scroll">
              <table className="results">
                <thead>
                  <tr><th>No</th><th>At</th><th>Jokey</th><th className="num">Kilo</th><th className="num">Form</th><th className="num">Koşu</th><th>Veri</th></tr>
                </thead>
                <tbody>
                  {race.runners.map((r) => (
                    <tr key={r.horse_id}>
                      <td><span className="silk sm" style={{ background: colorFor(r.program_no) }}>{r.program_no}</span></td>
                      <td>{r.name}</td>
                      <td>{r.jockey ?? '—'}{r.jockey_changed ? ' *' : ''}</td>
                      <td className="num">{r.weight_kg ?? '—'}</td>
                      <td className="num">{r.form.score?.toFixed(0) ?? '—'}</td>
                      <td className="num">{r.form.runs_used}</td>
                      <td><span className={`tag ${r.form.status === 'NO_DATA' ? 'warn' : r.form.status === 'DEMO' ? 'demo' : ''}`}>{STATUS_TR[r.form.status] ?? r.form.status}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="fine">
              Form puanı 0–100 (50 = ortalama). Bileşenler: hız/derece, finiş gücü, tempo dayanıklılığı, fazladan yol, rakip kalitesi, gelişim eğilimi.
              Ölçülemeyen bileşenler (ör. ara derece olmadan finiş gücü) hesaba katılmaz; uydurulmaz.
              {race.geometry.assumed && ' Pist geometrisi genel varsayımdır (son düzlük 400 m).'}
            </p>
          </section>
        </>
      )}
      <footer className="fine">
        HorseIQ — bahis/kupon entegrasyonu yoktur. Sanal sonuçlar kazanç garantisi veya doğrulanmış olasılık değildir. Motor {meta?.engine ?? ''}.
      </footer>
    </main>
  )
}

function SettingsPanel({ settings, onChange }: { settings: FormSettings; onChange: (p: Partial<FormSettings>) => void }) {
  return (
    <div className="settings">
      <fieldset>
        <legend>Geçmiş performans modu</legend>
        <label className="radio">
          <input type="radio" checked={settings.mode === 'days'} onChange={() => onChange({ mode: 'days' })} />
          Son
          <input type="number" min={30} max={1095} value={settings.days} disabled={settings.mode !== 'days'}
            onChange={(e) => onChange({ days: Math.max(30, Math.min(1095, Number(e.target.value) || 400)) })} />
          gün (tüm uygun koşular)
        </label>
        <label className="radio">
          <input type="radio" checked={settings.mode === 'races'} onChange={() => onChange({ mode: 'races' })} />
          Son
          <select value={settings.races} disabled={settings.mode !== 'races'} onChange={(e) => onChange({ races: Number(e.target.value) })}>
            {[1, 2, 3, 5, 10, 15, 20].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          uygun koşu (tarih sınırı yok)
        </label>
      </fieldset>
      <fieldset>
        <legend>Geçmiş koşuları hangi koşullarda ara?</legend>
        <label>
          Hipodrom
          <select value={settings.track_scope} onChange={(e) => onChange({ track_scope: e.target.value as 'same' | 'any' })}>
            <option value="same">Aynı hipodrom</option>
            <option value="any">Tüm hipodromlar</option>
          </select>
        </label>
        <label>
          Pist
          <select value={settings.surface_scope} onChange={(e) => onChange({ surface_scope: e.target.value as 'same' | 'any' })}>
            <option value="same">Aynı pist türü</option>
            <option value="any">Tüm pistler</option>
          </select>
        </label>
        <label>
          Mesafe
          <select value={settings.distance_tolerance_m ?? 'any'} onChange={(e) => onChange({ distance_tolerance_m: e.target.value === 'any' ? null : Number(e.target.value) })}>
            <option value={100}>±100 m</option>
            <option value={200}>±200 m</option>
            <option value={400}>±400 m</option>
            <option value="any">Tüm mesafeler</option>
          </select>
        </label>
      </fieldset>
      <p className="fine">Önce bu koşullara uyan koşular bulunur, sonra seçilen moda göre en yeniler alınır. Yalnızca yarış tarihinden önceki sonuçlar kullanılır.</p>
    </div>
  )
}
