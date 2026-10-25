import { useEffect, useState } from "react"
import { useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { PaperIn, PaperPreview } from "../../api/types"
import { Alert, Badge, Button, Dialog, Field, inputClass, Loading } from "../../ui"
import { fmt, ko, usd, weight } from "../../lib/format"

/** 리포트 → 모의투자 시작: 조건을 고르고 미리보기(시작 비중·배분)를 확인한 뒤에만 등록한다 (Module6 §3). */
export function StartPaperDialog({ reportId, close }: { reportId: string; close: () => void }) {
  const svc = useService()
  const [form, setForm] = useState<PaperIn>({ report_id: reportId })
  const [preview, setPreview] = useState<PaperPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<"preview" | "create" | "">("")
  const [stage, setStage] = useState<"form" | "confirm">("form")

  const load = async (f: PaperIn): Promise<boolean> => {
    setBusy("preview"); setError(null)
    try { const p = await svc.previewPaper(f); setPreview(p); setForm({ ...f, strategy_id: p.strategy.id, start_date: p.start_date, initial_amount: p.initial_capital.amount, currency: p.initial_capital.currency, monthly_contribution: p.contribution.monthly_amount ?? 0 }); return true } catch (e) { setError(errorMessage(e)); return false } finally { setBusy("") }
  }
  const switchCurrency = (cur: "KRW" | "USD") => {  // 통화를 바꾸면 금액도 미리보기 환율로 환산한다
    const fx = preview?.initial_capital.fx_rate ?? 1
    setForm((f) => {
      const amt = Number(f.initial_amount ?? 0)
      const conv = f.currency === cur ? amt : cur === "USD" ? Math.round(amt / fx) : Math.round(amt * fx)
      return { ...f, currency: cur, initial_amount: conv }
    })
  }
  useEffect(() => { void load({ report_id: reportId }) }, [reportId]) // eslint-disable-line react-hooks/exhaustive-deps

  const create = async () => {
    setBusy("create"); setError(null)
    try { const d = await svc.createPaper(form); close(); navigate({ page: "paper", paperId: d.portfolio.paper_id }) } catch (e) { setError(errorMessage(e)) } finally { setBusy("") }
  }
  const set = (k: keyof PaperIn, v: unknown) => setForm((f) => ({ ...f, [k]: v }))

  return (
    <Dialog title="모의투자 시작" close={close}>
      <div className="space-y-5 text-sm text-slate-700">
        <p>이 리포트의 전략을 가상 자본으로 따라갑니다. 실제 매매는 하지 않습니다. 시작하면 서버가 거래일마다 평가하고, 정해진 날에 비중을 다시 맞춥니다.</p>
        {error && <Alert tone="error" title="진행할 수 없습니다">{error}<div className="mt-2 flex gap-2"><Button variant="secondary" onClick={() => void load(form)} disabled={busy !== ""}>다시 시도</Button><Button variant="ghost" onClick={close}>닫기</Button></div></Alert>}
        {!preview && busy === "preview" && <Loading label="시작 조건을 계산하는 중…" />}
        {preview && stage === "form" && (
          <>
            <div className="grid grid-cols-2 gap-4">
              <Field label="전략" help="리포트에서 검증한 포트폴리오 중 하나">
                <select className={inputClass} value={form.strategy_id ?? ""} onChange={(e) => set("strategy_id", e.target.value)}>
                  {preview.strategy_options.map((o) => <option key={o.id} value={o.id}>{o.name_ko}{o.chosen ? " · 리포트 선택안" : o.recommended ? " · 추천" : ""} ({o.status === "pass" ? "통과" : o.status === "warn" ? "주의" : "미통과"})</option>)}
                </select>
              </Field>
              <Field label="시작일" help={`리포트 기준일 ${preview.report_as_of} 이후, 자료가 있는 마지막 날 ${preview.data_ceiling} 까지`}>
                <input className={inputClass} type="date" value={form.start_date ?? ""} min={preview.report_as_of} max={preview.data_ceiling} onChange={(e) => set("start_date", e.target.value)} />
              </Field>
              <Field label="가상 초기자본">
                <div className="flex gap-2">
                  <input className={inputClass} type="number" min={1} value={form.initial_amount ?? ""} onChange={(e) => set("initial_amount", Number(e.target.value))} />
                  <select className={`${inputClass} w-28`} value={form.currency ?? "KRW"} onChange={(e) => switchCurrency(e.target.value as "KRW" | "USD")}><option value="KRW">KRW</option><option value="USD">USD</option></select>
                </div>
              </Field>
              <Field label="월 적립액" help="0이면 적립 없음. 매월 적립일은 프로필 값을 따릅니다">
                <input className={inputClass} type="number" min={0} value={form.monthly_contribution ?? 0} onChange={(e) => set("monthly_contribution", Number(e.target.value))} />
              </Field>
            </div>
            <div className="flex justify-end gap-2"><Button variant="ghost" onClick={close}>취소</Button><Button onClick={async () => { if (await load(form)) setStage("confirm") }} disabled={busy !== ""}>{busy === "preview" ? "계산하는 중…" : "시작 조건 확인"}</Button></div>
          </>
        )}
        {preview && stage === "confirm" && (
          <>
            <div className="flex flex-wrap gap-2">
              <Badge tone="blue">{preview.strategy.name_ko}</Badge>
              <Badge tone="slate">시작 {preview.start_date}</Badge>
              <Badge tone="slate">{fmt(preview.initial_capital.amount, preview.initial_capital.currency === "KRW" ? "krw" : "usd")} = {usd(preview.initial_capital.usd)} ({preview.initial_capital.fx_date} 환율 {preview.initial_capital.fx_rate.toFixed(2)})</Badge>
              <Badge tone="slate">리밸런싱 {preview.rebalance_rule.count}×{ko(preview.rebalance_rule.unit)}</Badge>
              {preview.contribution.enabled && <Badge tone="slate">월 적립 {fmt(preview.contribution.monthly_amount ?? 0, preview.contribution.currency === "KRW" ? "krw" : "usd")} · {preview.contribution.day}일</Badge>}
            </div>
            {preview.reconstructed_at_start && <Alert tone="warning" title="시작일이 리포트 기준일보다 늦어 비중을 다시 계산했습니다">리포트 비중과 다른 종목이 있으면 아래 표의 차이 열에 표시됩니다. 종목은 그대로이고 비중만 다릅니다.</Alert>}
            {preview.warnings.map((w, i) => <Alert key={i} tone="warning" title="알림">{w}</Alert>)}
            <div className="max-h-72 overflow-auto rounded-xl border border-slate-200">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs font-semibold text-slate-500"><tr><th className="px-3 py-2">종목</th><th className="px-3 py-2 text-right">시작 비중</th><th className="px-3 py-2 text-right">리포트 비중</th><th className="px-3 py-2 text-right">차이</th><th className="px-3 py-2 text-right">배분 (USD)</th><th className="px-3 py-2 text-right">배분 (KRW)</th></tr></thead>
                <tbody>
                  {preview.allocation.map((a) => { const d = preview.weight_diff.find((x) => x.ticker === a.ticker); return (
                    <tr key={a.ticker} className="border-t border-slate-100"><td className="px-3 py-2 font-medium text-slate-900">{a.ticker}</td><td className="px-3 py-2 text-right">{weight(a.weight)}</td><td className="px-3 py-2 text-right text-slate-500">{weight(d?.report ?? 0)}</td><td className={`px-3 py-2 text-right ${d && Math.abs(d.delta) > 0.0005 ? "text-blue-700" : "text-slate-400"}`}>{d ? `${d.delta >= 0 ? "+" : ""}${weight(d.delta)}` : "–"}</td><td className="px-3 py-2 text-right">{usd(a.usd)}</td><td className="px-3 py-2 text-right">{fmt(a.krw, "krw")}</td></tr>
                  ) })}
                  {preview.cash_weight > 0.0005 && <tr className="border-t border-slate-100 bg-slate-50"><td className="px-3 py-2 font-medium text-slate-700">현금</td><td className="px-3 py-2 text-right">{weight(preview.cash_weight)}</td><td className="px-3 py-2" colSpan={2} /><td className="px-3 py-2 text-right">{usd(preview.initial_capital.usd * preview.cash_weight)}</td><td className="px-3 py-2 text-right">{fmt(preview.initial_capital.usd * preview.cash_weight * preview.initial_capital.fx_rate, "krw")}</td></tr>}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-slate-500">시작일 종가(USD 환산)로 소수 주식까지 사며, 거래대금의 0.05%를 수수료로 뺍니다. 여기 보이는 비중이 그대로 적용됩니다.</p>
            <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setStage("form")}>조건 바꾸기</Button><Button onClick={create} disabled={busy !== ""}>{busy === "create" ? "등록하는 중…" : "이 조건으로 시작"}</Button></div>
          </>
        )}
      </div>
    </Dialog>
  )
}
