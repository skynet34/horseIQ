import type { ActualRow, OrderRow, RaceDetail } from '../api'
import { colorFor } from './RaceTrack'

export const fmtTime = (s: number | null | undefined) => {
  if (s == null) return '—'
  const m = Math.floor(s / 60)
  const rest = s - m * 60
  return `${m}:${rest.toFixed(2).padStart(5, '0')}`
}

const fmtLen = (x: number | undefined) => (x == null ? '' : `${x.toLocaleString('tr-TR', { maximumFractionDigits: 1 })} boy`)

export function Podium({ order }: { order: OrderRow[] }) {
  return (
    <div className="podium">
      {order.slice(0, 3).map((o) => (
        <div key={o.horse_id} className={`podium-item p${o.pos}`}>
          <span className="podium-pos">{o.pos}.</span>
          <span className="silk" style={{ background: colorFor(o.program_no) }}>{o.program_no}</span>
          <span className="podium-name">{o.name}</span>
          <span className="podium-time">{fmtTime(o.time_s)}</span>
        </div>
      ))}
    </div>
  )
}

export function ResultsTable({ order, race }: { order: OrderRow[]; race: RaceDetail }) {
  const statusOf = (hid: number) => race.runners.find((r) => r.horse_id === hid)?.form.status
  return (
    <div className="table-scroll">
      <table className="results">
        <thead>
          <tr>
            <th>#</th>
            <th>At</th>
            <th className="num">Derece</th>
            <th className="num">Önündeki ata</th>
            <th className="num">Kazanana</th>
          </tr>
        </thead>
        <tbody>
          {order.map((o) => (
            <tr key={o.horse_id}>
              <td>{o.pos}</td>
              <td>
                <span className="silk sm" style={{ background: colorFor(o.program_no) }}>{o.program_no}</span> {o.name}
                {statusOf(o.horse_id) === 'NO_DATA' && <span className="tag warn" title="Filtreye uygun geçmiş koşu yok: profil varsayımsal">veri yok</span>}
              </td>
              <td className="num">{fmtTime(o.time_s)}</td>
              <td className="num">{o.pos === 1 ? 'Kazanan' : `${o.gap_prev_text ?? ''}`}</td>
              <td className="num">{o.pos === 1 ? '—' : `${fmtLen(o.gap_win_len)} · ${o.gap_win_s?.toFixed(2)} sn`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="fine">Boy farkı yaklaşıktır: saniye farkı, atın ortalama hızıyla metreye çevrilip 1 boy ≈ 2,4 m kabul edilerek hesaplanır.</p>
    </div>
  )
}

export function ActualTable({ actual }: { actual: ActualRow[] }) {
  return (
    <div className="table-scroll">
      <table className="results">
        <thead>
          <tr>
            <th>#</th>
            <th>At</th>
            <th className="num">Resmî derece</th>
            <th className="num">Fark</th>
          </tr>
        </thead>
        <tbody>
          {actual.map((a) => (
            <tr key={a.horse_id}>
              <td>{a.finish_pos ?? '—'}</td>
              <td>{a.program_no ? <span className="silk sm" style={{ background: colorFor(a.program_no) }}>{a.program_no}</span> : null} {a.name}</td>
              <td className="num">{fmtTime(a.finish_time_s)}</td>
              <td className="num">{a.margin_text ?? (a.finish_pos === 1 ? 'Kazanan' : '')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
