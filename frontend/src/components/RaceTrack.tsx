import { useEffect, useRef, useState } from 'react'
import type { RaceDetail, SimEvent, SimRun } from '../api'

// Silk colours by program number (cycled). Purely visual.
export const COLORS = [
  '#e5484d', '#3e7bfa', '#30a46c', '#f5a524', '#8e4ec6', '#f76b15', '#12a594', '#d6409f',
  '#94ba2c', '#a18072', '#0090ff', '#e54666', '#46a758', '#6e56cf', '#ffb224', '#ad7f58',
]
export const colorFor = (no: number) => COLORS[(no - 1) % COLORS.length]

interface Props {
  race: RaceDetail
  run: SimRun | null
  speed: number // playback multiplier only; the result is already computed
  playKey: number // bump to restart playback
  highlightHorse?: number
  onFinished?: () => void
}

const TRACK_WIDTH_M = 18

export default function RaceTrack({ race, run, speed, playKey, highlightHorse, onFinished }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const stripRef = useRef<HTMLCanvasElement>(null)
  const simTime = useRef(0)
  const speedRef = useRef(speed)
  const [clock, setClock] = useState(0)
  const [toasts, setToasts] = useState<SimEvent[]>([])
  speedRef.current = speed

  useEffect(() => {
    simTime.current = 0
    setClock(0)
    setToasts([])
    if (!run) {
      draw(0)
      return
    }
    let raf = 0
    let last = performance.now()
    let done = false
    const end = run.frames[run.frames.length - 1]?.t ?? 0
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000)
      last = now
      simTime.current = Math.min(end, simTime.current + dt * speedRef.current)
      draw(simTime.current)
      setClock(simTime.current)
      setToasts(run.events.filter((e) => e.t <= simTime.current && e.t > simTime.current - 4))
      if (simTime.current >= end) {
        if (!done) {
          done = true
          onFinished?.()
        }
        return
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run, playKey])

  useEffect(() => {
    const onResize = () => draw(simTime.current)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  })

  function positions(t: number): [number, number, number, number][] {
    if (!run || run.frames.length === 0) return race.runners.map((r) => [0, ((r.gate ?? r.program_no) - 1) * 1.05, 0, 1])
    const f = run.frames
    let i = f.findIndex((fr) => fr.t >= t)
    if (i <= 0) return f[Math.max(0, i)].h
    if (i === -1) return f[f.length - 1].h
    const a = f[i - 1]
    const b = f[i]
    const k = (t - a.t) / Math.max(1e-6, b.t - a.t)
    return a.h.map((ha, j) => {
      const hb = b.h[j]
      return [ha[0] + (hb[0] - ha[0]) * k, ha[1] + (hb[1] - ha[1]) * k, ha[2] + (hb[2] - ha[2]) * k, ha[3]] as [number, number, number, number]
    })
  }

  function draw(t: number) {
    const cv = canvasRef.current
    const strip = stripRef.current
    if (!cv || !strip) return
    const dpr = window.devicePixelRatio || 1
    const W = cv.clientWidth
    const L = race.geometry.home_straight_m
    const R = race.geometry.turn_radius_m
    const worldW = L + 2 * (R + TRACK_WIDTH_M) + 20
    const worldH = 2 * (R + TRACK_WIDTH_M) + 20
    const scale = W / worldW
    const H = worldH * scale
    cv.height = H * dpr
    cv.style.height = `${H}px`
    cv.width = W * dpr
    const ctx = cv.getContext('2d')!
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, W, H)
    const cx0 = (10 + R + TRACK_WIDTH_M) * scale // centre of left turn
    const cx1 = cx0 + L * scale // centre of right turn
    const cy = H / 2
    const r0 = R * scale

    // infield + track band
    const stadium = (rad: number) => {
      ctx.beginPath()
      ctx.moveTo(cx0, cy + rad)
      ctx.lineTo(cx1, cy + rad)
      ctx.arc(cx1, cy, rad, Math.PI / 2, -Math.PI / 2, true)
      ctx.lineTo(cx0, cy - rad)
      ctx.arc(cx0, cy, rad, -Math.PI / 2, Math.PI / 2, true)
      ctx.closePath()
    }
    const turf = race.surface === 'TURF'
    stadium(r0 + TRACK_WIDTH_M * scale)
    ctx.fillStyle = turf ? '#2f7d4a' : '#b08d5b'
    ctx.fill()
    stadium(r0)
    ctx.fillStyle = '#1d5236'
    ctx.fill()
    ctx.strokeStyle = 'rgba(255,255,255,.85)'
    ctx.lineWidth = 1.5
    ctx.stroke()

    // finish post: end of the bottom (home) straight
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 3
    ctx.beginPath()
    ctx.moveTo(cx1, cy + r0)
    ctx.lineTo(cx1, cy + r0 + TRACK_WIDTH_M * scale)
    ctx.stroke()
    ctx.fillStyle = '#fff'
    ctx.font = '600 11px system-ui'
    ctx.fillText('FİNİŞ', cx1 - 16, cy + r0 + TRACK_WIDTH_M * scale + 13)

    // runner positions: course laid out backwards from the finish
    const C = 2 * L + 2 * Math.PI * R
    const point = (s: number, lane: number) => {
      const rem = race.distance_m - s
      let u = (((L - rem) % C) + C) % C // 0 = start of home straight (bottom-left)
      const off = (lane + 1.2) * scale
      if (u < L) return [cx0 + u * scale, cy + r0 + off]
      u -= L
      if (u < Math.PI * R) {
        const a = Math.PI / 2 - u / R
        return [cx1 + (r0 + off) * Math.cos(a), cy + (r0 + off) * Math.sin(a)]
      }
      u -= Math.PI * R
      if (u < L) return [cx1 - u * scale, cy - r0 - off]
      u -= L
      const a = -Math.PI / 2 - u / R
      return [cx0 + (r0 + off) * Math.cos(a), cy + (r0 + off) * Math.sin(a)]
    }

    const pos = positions(t)
    const order = pos.map((p, i) => ({ p, i })).sort((a, b) => a.p[0] - b.p[0]) // draw leaders last
    const leadS = Math.max(...pos.map((p) => p[0]))
    const rad = Math.max(6, Math.min(10, 2.6 * scale * 2))
    for (const { p, i } of order) {
      const runner = race.runners[i]
      const [x, y] = point(p[0], p[1])
      ctx.beginPath()
      ctx.arc(x, y, rad, 0, Math.PI * 2)
      ctx.fillStyle = colorFor(runner.program_no)
      ctx.fill()
      ctx.lineWidth = runner.horse_id === highlightHorse ? 3 : 1.5
      ctx.strokeStyle = runner.horse_id === highlightHorse ? '#ffe066' : p[0] === leadS && t > 0 ? '#fff' : 'rgba(0,0,0,.5)'
      ctx.stroke()
      ctx.fillStyle = '#fff'
      ctx.font = `700 ${rad < 8 ? 9 : 11}px system-ui`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(String(runner.program_no), x, y + 0.5)
    }
    ctx.textAlign = 'start'
    ctx.textBaseline = 'alphabetic'

    // linear strip: last 40 lengths behind the leader, shows gaps legibly
    const SW = strip.clientWidth
    const SH = 34
    strip.width = SW * dpr
    strip.height = SH * dpr
    strip.style.height = `${SH}px`
    const sx = strip.getContext('2d')!
    sx.setTransform(dpr, 0, 0, dpr, 0, 0)
    sx.clearRect(0, 0, SW, SH)
    sx.fillStyle = 'rgba(255,255,255,.06)'
    sx.fillRect(0, 0, SW, SH)
    const span = 40 * 2.4
    const minS = leadS - span
    for (const { p, i } of order) {
      const runner = race.runners[i]
      const x = 14 + ((p[0] - minS) / span) * (SW - 28)
      if (x < 4) continue
      sx.beginPath()
      sx.arc(x, SH / 2, 9, 0, Math.PI * 2)
      sx.fillStyle = colorFor(runner.program_no)
      sx.fill()
      sx.fillStyle = '#fff'
      sx.font = '700 10px system-ui'
      sx.textAlign = 'center'
      sx.textBaseline = 'middle'
      sx.fillText(String(runner.program_no), x, SH / 2 + 0.5)
    }
  }

  const leader = run ? Math.max(...positions(clock).map((p) => p[0])) : 0
  return (
    <div className="track-wrap">
      <canvas ref={canvasRef} className="track-canvas" aria-label="Sanal pist" />
      <canvas ref={stripRef} className="strip-canvas" aria-label="Aradaki farklar (lider ve arkasındaki 40 boy)" />
      <div className="track-hud">
        <span>{run ? `${Math.min(race.distance_m, Math.round(leader))} / ${race.distance_m} m` : `${race.distance_m} m · start`}</span>
        <span>{clock.toFixed(1)} sn</span>
      </div>
      <div className="toasts" aria-live="polite">
        {toasts.slice(-3).map((e, k) => (
          <div key={`${e.t}-${e.horse_id}-${k}`} className={e.intervention ? 'toast iv' : 'toast'}>
            {e.text}
          </div>
        ))}
      </div>
    </div>
  )
}
