import { useEffect, useState } from "react"
import { useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { PaperIn, PaperPreview } from "../../api/types"
import { Alert, Button, Dialog, Field, inputClass, Loading } from "../../ui"
import { fmt, usd, weight } from "../../lib/format"
import { rebalanceText } from "../profile/format"
import { fxText, inCur } from "./money"
import { MockTag } from "../report/proposedView"
import { emptyNameError, type NameMode, PaperNameChoice } from "./PaperName"
import { paperBasis, samePapers } from "./paperLabel"
import { useResource } from "../../state/useResource"

const statusKo = (s: string) => (s === "pass" ? "검증 통과" : s === "warn" ? "검증 주의" : "검증 미통과")

/** 리포트 → 모의투자 시작: 조건을 고르고 미리보기(시작 비중·배분)를 확인한 뒤에만 등록한다 (Module6 §3). */
export function StartPaperDialog({ reportId, close }: { reportId: string; close: () => void }) {
  const svc = useService()
  const [form, setForm] = useState<PaperIn>({ report_id: reportId })
  const [preview, setPreview] = useState<PaperPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<"preview" | "create" | "">("")
  const [stage, setStage] = useState<"form" | "confirm">("form")
  // 모의투자 이름 (제안 기능): 서비스에 이름 연동(setPaperName·getReportName)이 있을 때만 고른다. 없으면 서버가 정한 이름 그대로.
  const [reportName, setReportName] = useState<string | null>(null)
  const [nameMode, setNameMode] = useState<NameMode>("linked")
  const [customName, setCustomName] = useState("")
  const [nameErr, setNameErr] = useState("")
  useEffect(() => { if (svc.setPaperName && svc.getReportName) svc.getReportName(reportId).then((n) => setReportName(n.display_ko), () => setReportName(null)) }, [svc, reportId])
  const paperName = nameMode === "custom" ? customName.trim() : reportName
  const existing = samePapers(useResource(() => svc.listPaper(), [svc]).data ?? [], reportId)  // 이 리포트로 이미 시작한 모의투자 (구분용)

  const load = async (f: PaperIn): Promise<boolean> => {
    setBusy("preview"); setError(null)
    try { const p = await svc.previewPaper(f); setPreview(p); setForm({ ...f, strategy_id: p.strategy.id, start_date: p.start_date, initial_amount: p.initial_capital.amount, currency: p.initial_capital.currency, monthly_contribution: p.contribution.monthly_amount ?? 0 }); return true } catch (e) { setError(errorMessage(e)); return false } finally { setBusy("") }
  }
  const switchCurrency = (cur: "KRW" | "USD") => {  // 통화를 바꾸면 초기자본·월 적립금을 미리보기 환율로 함께 환산한다
    const fx = preview?.initial_capital.fx_rate ?? 1
    setForm((f) => {
      const conv = (v: number) => (f.currency === cur ? v : cur === "USD" ? Math.round(v / fx) : Math.round(v * fx))
      return { ...f, currency: cur, initial_amount: conv(Number(f.initial_amount ?? 0)), monthly_contribution: conv(Number(f.monthly_contribution ?? 0)) }
    })
  }
  useEffect(() => { void load({ report_id: reportId }) }, [reportId]) // eslint-disable-line react-hooks/exhaustive-deps

  const create = async () => {
    setBusy("create"); setError(null)
    try {
      const d = await svc.createPaper(reportName && nameMode === "custom" ? { ...form, name: { mode: "custom", name_ko: customName.trim() } } : form)  // 이름도 등록 때 함께 (따로 부르면 등록만 되고 이름은 실패할 수 있다)
      close(); navigate({ page: "paper", paperId: d.portfolio.paper_id })
    } catch (e) { setError(errorMessage(e)) } finally { setBusy("") }
  }
  const set = (k: keyof PaperIn, v: unknown) => setForm((f) => ({ ...f, [k]: v }))
  const picked = preview?.strategy_options.find((o) => o.id === form.strategy_id)
  const cur = preview?.initial_capital.currency ?? "KRW"

  return (
    <Dialog title="모의투자 시작" close={close}>
      <div className="space-y-5 p-4 text-sm text-slate-700 sm:p-6">
        <p>이 리포트의 전략을 가상 자본으로 따라갑니다. 실제 매매는 하지 않습니다. 시작하면 서버가 거래일마다 평가하고, 정해진 날에 비중을 다시 맞춥니다.</p>
        {error && <Alert tone="error" title="진행할 수 없습니다">{error}<div className="mt-2 flex gap-2"><Button variant="secondary" onClick={() => void load(form)} disabled={busy !== ""}>다시 시도</Button><Button variant="ghost" onClick={close}>닫기</Button></div></Alert>}
        {!preview && busy === "preview" && <Loading label="시작 조건을 계산하는 중…" />}
        {preview && stage === "form" && (
          <>
            {existing.length > 0 && (
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
                <p className="font-semibold text-slate-800">이 리포트로 이미 시작한 모의투자 {existing.length}개</p>
                <ul className="mt-1 space-y-0.5">{existing.map((x) => <li key={x.paper_id} className="break-words">{paperBasis(x)}{x.status === "stopped" ? " · 중지됨" : ""}</li>)}</ul>
                <p className="mt-1 text-slate-500">전략·시작일·초기 투자금을 다르게 하면 목록에서 구분하기 쉽습니다.</p>
              </div>
            )}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2"><Field label="전략" help="리포트에서 검증한 포트폴리오 중 하나">
                <select className={inputClass} value={form.strategy_id ?? ""} onChange={(e) => set("strategy_id", e.target.value)}>
                  {preview.strategy_options.map((o) => <option key={o.id} value={o.id}>{o.name_ko}{o.chosen ? " · 리포트 선택안" : o.recommended ? " · 추천" : ""} ({o.status === "pass" ? "통과" : o.status === "warn" ? "주의" : "미통과"})</option>)}
                </select>
              </Field>{picked && <p className="mt-1.5 break-words text-xs leading-5 text-slate-600">선택: <b>{picked.name_ko}</b> · {statusKo(picked.status)}{picked.chosen ? " · 리포트 선택안" : picked.recommended ? " · 추천" : ""}</p>}</div>
              <Field label="시작일" help={`리포트 기준일 ${preview.report_as_of} 이후, 자료가 있는 마지막 날 ${preview.data_ceiling} 까지`}>
                <input className={inputClass} type="date" value={form.start_date ?? ""} min={preview.report_as_of} max={preview.data_ceiling} onChange={(e) => set("start_date", e.target.value)} />
              </Field>
              <Field label="가상 초기자본">
                <div className="flex gap-2">
                  <input className={inputClass} type="number" min={0} value={form.initial_amount ?? ""} onChange={(e) => set("initial_amount", Number(e.target.value))} />
                  <select className={`${inputClass} w-28`} value={form.currency ?? "KRW"} onChange={(e) => switchCurrency(e.target.value as "KRW" | "USD")}><option value="KRW">KRW</option><option value="USD">USD</option></select>
                </div>
              </Field>
              <Field label={`월 적립액 (${form.currency === "USD" ? "USD" : "원"})`} help="0이면 적립 없음. 적립일은 이 분석에 적용된 값을 따릅니다">
                <input className={inputClass} type="number" min={0} value={form.monthly_contribution ?? 0} onChange={(e) => set("monthly_contribution", Number(e.target.value))} />
              </Field>
            </div>
            {reportName && <PaperNameChoice reportName={reportName} mode={nameMode} setMode={setNameMode} value={customName} setValue={setCustomName} error={nameErr} setError={setNameErr} />}
            <div className="flex justify-end gap-2"><Button variant="ghost" onClick={close}>취소</Button><Button onClick={async () => { if (reportName && nameMode === "custom" && !customName.trim()) { setNameErr(emptyNameError); return } if (await load(form)) setStage("confirm") }} disabled={busy !== ""}>{busy === "preview" ? "계산하는 중…" : "시작 조건 확인"}</Button></div>
          </>
        )}
        {preview && stage === "confirm" && (
          <>
            <dl className="grid grid-cols-1 gap-3 rounded-xl bg-slate-50 p-4 sm:grid-cols-2">
              {reportName && <div className="sm:col-span-2"><dt className="flex items-center text-xs font-semibold text-slate-500">모의투자 이름<MockTag /></dt><dd className="mt-0.5 break-words font-semibold text-slate-900">{paperName}</dd><dd className="text-xs text-slate-500">{nameMode === "linked" ? "리포트 이름과 연동 · 리포트 이름을 바꾸면 함께 바뀝니다" : "직접 입력 · 리포트 이름을 바꿔도 그대로입니다"}</dd></div>}
              <div className="sm:col-span-2"><dt className="text-xs font-semibold text-slate-500">전략</dt><dd className="mt-0.5 break-words font-semibold text-slate-900">{preview.strategy.name_ko}</dd></div>
              <div><dt className="text-xs font-semibold text-slate-500">시작일</dt><dd className="mt-0.5 font-semibold text-slate-900">{preview.start_date}</dd></div>
              <div><dt className="text-xs font-semibold text-slate-500">통화</dt><dd className="mt-0.5 font-semibold text-slate-900">{cur === "KRW" ? "원 (KRW)" : "달러 (USD)"}</dd></div>
              <div><dt className="text-xs font-semibold text-slate-500">초기자본</dt><dd className="mt-0.5 font-semibold text-slate-900">{inCur(preview.initial_capital.amount, cur)}</dd><dd className="text-xs text-slate-500">{usd(preview.initial_capital.usd)} · {fxText(preview.initial_capital.fx_rate, preview.initial_capital.fx_date)}</dd></div>
              <div><dt className="text-xs font-semibold text-slate-500">월 적립금</dt><dd className="mt-0.5 font-semibold text-slate-900">{preview.contribution.enabled ? `${inCur(preview.contribution.monthly_amount ?? 0, cur)} · 매월 ${preview.contribution.day}일` : "없음"}</dd></div>
              <div><dt className="text-xs font-semibold text-slate-500">현금 비중</dt><dd className="mt-0.5 font-semibold text-slate-900">{weight(preview.cash_weight)}</dd></div>
              <div><dt className="text-xs font-semibold text-slate-500">리밸런싱</dt><dd className="mt-0.5 font-semibold text-slate-900">{preview.rebalance_rule.count === 0 ? "하지 않음" : rebalanceText(preview.rebalance_rule as never)}</dd></div>
            </dl>
            {preview.reconstructed_at_start && <Alert tone="warning" title="시작일이 리포트 기준일보다 늦어 비중을 다시 계산했습니다">리포트 비중과 다른 종목이 있으면 아래 표의 차이 열에 표시됩니다. 종목은 그대로이고 비중만 다릅니다.</Alert>}
            {preview.warnings.map((w, i) => <Alert key={i} tone="warning" title="알림">{w}</Alert>)}
            <div className="max-h-72 overflow-auto rounded-xl border border-slate-200">
              <table className="w-full min-w-[420px] text-sm">
                <thead className="bg-slate-50 text-left text-xs font-semibold text-slate-500"><tr><th className="px-3 py-2">종목</th><th className="px-3 py-2 text-right">시작 비중</th><th className="px-3 py-2 text-right">리포트 비중</th><th className="px-3 py-2 text-right">차이</th><th className="px-3 py-2 text-right">배분 ({cur === "KRW" ? "원" : "USD"})</th></tr></thead>
                <tbody>
                  {preview.allocation.map((a) => { const d = preview.weight_diff.find((x) => x.ticker === a.ticker); return (
                    <tr key={a.ticker} className="border-t border-slate-100"><td className="px-3 py-2 font-medium text-slate-900">{a.ticker}</td><td className="px-3 py-2 text-right">{weight(a.weight)}</td><td className="px-3 py-2 text-right text-slate-500">{weight(d?.report ?? 0)}</td><td className={`px-3 py-2 text-right ${d && Math.abs(d.delta) > 0.0005 ? "text-blue-700" : "text-slate-400"}`}>{d ? fmt(d.delta, "pp") : "–"}</td><td className="px-3 py-2 text-right tabular-nums">{cur === "KRW" ? fmt(a.krw, "krw") : usd(a.usd)}</td></tr>
                  ) })}
                  {preview.cash_weight > 0.0005 && <tr className="border-t border-slate-100 bg-slate-50"><td className="px-3 py-2 font-medium text-slate-700">현금</td><td className="px-3 py-2 text-right">{weight(preview.cash_weight)}</td><td className="px-3 py-2" colSpan={2} /><td className="px-3 py-2 text-right tabular-nums">{inCur(preview.initial_capital.amount * preview.cash_weight, cur)}</td></tr>}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-slate-500">시작일 종가(USD 환산)로 소수 주식까지 사며, 거래대금의 0.05%를 수수료로 뺍니다. 여기 보이는 비중이 그대로 적용됩니다.{preview.allocation_basis_ko && " 초기자본이 0원이라 금액은 첫 적립금 기준이며, 첫 적립일에 처음 매수합니다."}</p>
            <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setStage("form")}>조건 바꾸기</Button><Button onClick={create} disabled={busy !== ""}>{busy === "create" ? "등록하는 중…" : "이 조건으로 시작"}</Button></div>
          </>
        )}
      </div>
    </Dialog>
  )
}
