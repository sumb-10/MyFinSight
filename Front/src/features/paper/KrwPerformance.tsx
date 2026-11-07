import type { ProposedFxDay, ProposedPaperKrw } from "../../api/proposed"
import { Disclosure } from "../../ui"
import { fmt, pct, usd } from "../../lib/format"
import { MockTag } from "../report/proposedView"
import { Part } from "../profile/parts"

// 원화 기준 성과·환율 적용 상태 (제안 기능): 서비스에 getPaperKrw 가 있을 때만 — 지금은 목업뿐.
// 값은 서비스가 준 것을 그대로 보여 주고 화면에서 환율을 곱해 다시 계산하지 않는다.

const won = (v: number) => `${Math.round(v).toLocaleString("ko-KR")}원`
const signedWon = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(Math.round(v)).toLocaleString("ko-KR")}원`
const signedUsd = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${usd(Math.abs(v))}`
const tone = (v: number | null) => (v == null ? "text-slate-500" : v >= 0 ? "text-emerald-700" : "text-red-700")

/** 환율 적용 상태 표시: 정상 / 직전 환율 대체 / 환율 없음(환산 불가). */
export function FxStatus({ f, short }: { f: ProposedFxDay; short?: boolean }) {
  if (f.status === "ok") return <span className="text-slate-500">{short ? "정상" : "그날 환율"}</span>
  if (f.status === "carried") return <span className="font-semibold text-amber-800" title={`이 날짜의 환율 자료가 없어 ${f.carried_from} 환율을 썼습니다`}>{short ? "직전 환율 대체" : `직전 환율 대체 (${f.carried_from})`}</span>
  return <span className="font-semibold text-red-700" title="환율 자료가 없어 원화로 환산하지 못했습니다">환율 없음 · 환산 불가</span>
}

export function KrwPerformance({ k }: { k: ProposedPaperKrw }) {
  const u = k.usd_same_basis
  const odd = k.fx.filter((f) => f.status !== "ok")
  const diff = k.fx_effect_pp
  return (
    <Part title="원화 기준 성과" aside={<MockTag />} desc="날짜별 환율로 계산한 원화 기준 성과입니다.">
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
        <div className="min-w-0"><p className="text-xs font-semibold text-slate-500">원화 평가액</p><p className="mt-1 text-2xl font-bold tabular-nums text-slate-950">{k.last.value_krw == null ? "환산 불가" : won(k.last.value_krw)}</p></div>
        <div className="min-w-0"><p className="text-xs font-semibold text-slate-500">원화 수익률 (넣은 원금 대비)</p><p className={`mt-1 text-2xl font-bold tabular-nums ${tone(k.return_krw)}`}>{k.return_krw == null ? "계산 불가" : pct(k.return_krw)}</p></div>
        <div className="min-w-0"><p className="text-xs font-semibold text-slate-500">원화 손익 금액</p><p className={`mt-1 text-2xl font-bold tabular-nums ${tone(k.gain_krw)}`}>{k.gain_krw == null ? "계산 불가" : signedWon(k.gain_krw)}</p></div>
      </div>
      {k.unavailable_reason_ko && <p role="note" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950"><b>원화 수익률을 계산하지 않았습니다.</b> {k.unavailable_reason_ko} 마지막 날 환율로 과거 원금을 거꾸로 환산하지 않습니다.</p>}

      <div className="overflow-x-auto rounded-xl border border-slate-200">
        <table className="w-full min-w-[480px] text-sm" aria-label="원화와 USD 기준 비교">
          <thead className="bg-slate-50 text-left text-xs font-semibold text-slate-500"><tr><th className="px-3 py-2">같은 방식(넣은 원금 대비)</th><th className="px-3 py-2 text-right">넣은 원금</th><th className="px-3 py-2 text-right">평가액</th><th className="px-3 py-2 text-right">손익</th><th className="px-3 py-2 text-right">수익률</th></tr></thead>
          <tbody>
            <tr className="border-t border-slate-100"><td className="px-3 py-2 font-semibold text-slate-900">원화 기준</td><td className="px-3 py-2 text-right tabular-nums">{k.contributions_krw_total == null ? "–" : won(k.contributions_krw_total)}</td><td className="px-3 py-2 text-right tabular-nums">{k.last.value_krw == null ? "–" : won(k.last.value_krw)}</td><td className={`px-3 py-2 text-right tabular-nums ${tone(k.gain_krw)}`}>{k.gain_krw == null ? "–" : signedWon(k.gain_krw)}</td><td className={`px-3 py-2 text-right font-semibold tabular-nums ${tone(k.return_krw)}`}>{k.return_krw == null ? "–" : pct(k.return_krw)}</td></tr>
            <tr className="border-t border-slate-100"><td className="px-3 py-2 font-semibold text-slate-900">USD 기준</td><td className="px-3 py-2 text-right tabular-nums">{usd(u.contributions_usd)}</td><td className="px-3 py-2 text-right tabular-nums">{usd(u.value_usd)}</td><td className={`px-3 py-2 text-right tabular-nums ${tone(u.gain_usd)}`}>{signedUsd(u.gain_usd)}</td><td className={`px-3 py-2 text-right font-semibold tabular-nums ${tone(u.return_usd)}`}>{pct(u.return_usd)}</td></tr>
          </tbody>
        </table>
      </div>
      {diff != null && (
        <p className="rounded-xl bg-slate-50 p-3 text-sm leading-6 text-slate-700">
          원화 수익률이 USD 수익률보다 <b>{fmt(Math.abs(diff), "pp").replace(/^[+−-]/, "")} {diff >= 0 ? "높습니다" : "낮습니다"}</b>.
          {k.fx_change != null && k.fx_start.rate && k.last.fx.rate && <> 같은 기간 환율이 1 USD = {k.fx_start.rate.toLocaleString("ko-KR")}원({k.fx_start.date}) → {k.last.fx.rate.toLocaleString("ko-KR")}원({k.last.date})으로 {(Math.abs(k.fx_change) * 100).toFixed(2)}% {k.fx_change >= 0 ? "올라(원화 약세) 원화로 본 평가액이 더 커졌습니다" : "내려(원화 강세) 원화로 본 평가액이 줄었습니다"}.</>}
        </p>
      )}

      <div className="space-y-2 border-t border-slate-100 pt-4">
        <p className="text-sm font-semibold text-slate-800">환율 적용 상태</p>
        <ul className="flex flex-wrap gap-2 text-xs" aria-label="환율 적용 상태 요약">
          <li className="rounded-lg border border-slate-200 bg-white px-2.5 py-1">그날 환율 사용 <b>{k.fx_counts.ok}일</b></li>
          <li className={`rounded-lg border px-2.5 py-1 ${k.fx_counts.carried ? "border-amber-200 bg-amber-50 text-amber-900" : "border-slate-200 bg-white"}`}>직전 환율 대체 <b>{k.fx_counts.carried}일</b></li>
          <li className={`rounded-lg border px-2.5 py-1 ${k.fx_counts.missing ? "border-red-200 bg-red-50 text-red-800" : "border-slate-200 bg-white"}`}>환율 없음(환산 불가) <b>{k.fx_counts.missing}일</b></li>
        </ul>
        {odd.length > 0 && (
          <Disclosure size="sm" title={`대체·환산 불가 날짜 ${odd.length}일 보기`}>
            <ul className="space-y-1 text-xs">{odd.map((f) => <li key={f.date} className="flex flex-wrap gap-x-3"><span className="w-24 tabular-nums text-slate-700">{f.date}</span><FxStatus f={f} />{f.rate != null && <span className="tabular-nums text-slate-500">1 USD = {f.rate.toLocaleString("ko-KR")}원</span>}</li>)}</ul>
          </Disclosure>
        )}
      </div>
    </Part>
  )
}
