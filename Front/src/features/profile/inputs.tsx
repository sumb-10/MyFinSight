import { cloneElement, useEffect, useId, useRef, useState } from "react"
import { Info, X } from "lucide-react"
import { inputClass } from "../../ui"

// 기본 투자조건 화면 전용 입력 부품. 저장 값의 형식(분수 비율·티커 문자열 목록)은 그대로 두고 입력 방식만 바꾼다.

const OPEN_EVENT = "profile-infotip-open"

/** ⓘ 버튼을 누르면 설명이 열린다 (마우스 오버가 아니라 눌러서 여닫으므로 터치·키보드에서도 쓸 수 있다). Esc·바깥 누르기로 닫히고, 한 번에 하나만 열린다. */
export function InfoTip({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!open) return
    const key = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false)
    const click = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    const other = (e: Event) => { if ((e as CustomEvent<string>).detail !== id) setOpen(false) }
    window.addEventListener("keydown", key); window.addEventListener("mousedown", click); window.addEventListener(OPEN_EVENT, other)
    return () => { window.removeEventListener("keydown", key); window.removeEventListener("mousedown", click); window.removeEventListener(OPEN_EVENT, other) }
  }, [open, id])
  const toggle = () => { if (!open) window.dispatchEvent(new CustomEvent(OPEN_EVENT, { detail: id })); setOpen(!open) }
  return (
    <span ref={ref} className="relative inline-flex align-middle">
      <button type="button" aria-label={`${label} 설명 보기`} aria-expanded={open} aria-controls={id} onClick={toggle} className={`rounded-full p-0.5 transition focus:outline-none focus:ring-2 focus:ring-blue-500 ${open ? "text-blue-700" : "text-slate-400 hover:text-blue-700"}`}><Info className="size-4" /></button>
      {open && <span id={id} role="note" className="absolute left-0 top-full z-30 mt-1.5 block w-72 max-w-[calc(100vw-2rem)] rounded-xl border border-slate-200 bg-white p-3 text-left text-xs font-normal leading-5 text-slate-600 shadow-lg">{children}</span>}
    </span>
  )
}

/** 이름 옆에 ⓘ 를 둘 수 있는 입력 칸. 입력 요소 하나를 children 으로 받아 이름표와 연결한다. */
export function InfoField({ label, info, help, error, children }: { label: string; info?: React.ReactNode; help?: React.ReactNode; error?: string; children: React.ReactElement<{ id?: string }> }) {
  const id = useId()
  return (
    <div>
      <div className="mb-2 flex items-center gap-1"><label htmlFor={id} className="text-sm font-semibold text-slate-700">{label}</label>{info && <InfoTip label={label}>{info}</InfoTip>}</div>
      {cloneElement(children, { id })}
      {error ? <p className="mt-1.5 text-xs font-medium text-red-600">{error}</p> : help && <p className="mt-1.5 text-xs leading-5 text-slate-500">{help}</p>}
    </div>
  )
}

/** 앞의 0 지우기: "05" → "5", "007" → "7" ("0", "0.5" 는 그대로). */
export const stripLeadingZeros = (s: string) => s.replace(/^(-?)0+(?=\d)/, "$1")

/** 숫자 칸. 0 이 들어 있던 칸에 숫자를 치면 앞의 0 을 지운다. type="number" 는 값이 같으면("05" == 5) React 가 화면 글자를 고치지 않아 여기서 직접 고친다. */
export function NumberInput({ value, onChange, className = inputClass, ...rest }: Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type"> & { value: number; onChange: (v: number) => void }) {
  return <input {...rest} type="number" className={className} value={value} onChange={(e) => { const clean = stripLeadingZeros(e.target.value); if (clean !== e.target.value) e.target.value = clean; onChange(Number(clean)) }} />
}

const round1 = (v: number) => Math.round(v * 1000) / 10  // 0.125 → 12.5

/** 슬라이더 + % 숫자 입력. value·min·max·step 은 분수(0.2 = 20%). 범위를 벗어난 숫자는 반영하지 않고 안내한다. */
export function PercentSlider({ label, value, min, max, step, onChange, info, help, error }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; info?: React.ReactNode; help?: React.ReactNode; error?: string }) {
  const id = useId()
  const [draft, setDraft] = useState<string | null>(null)  // 입력 중인 글자 (null = 저장 값 그대로 표시)
  const [hint, setHint] = useState("")
  const lo = round1(min), hi = round1(max)
  const type = (raw: string) => {
    const s = stripLeadingZeros(raw)
    setDraft(s)
    const n = Number(s)
    if (s.trim() === "" || !Number.isFinite(n)) { setHint("숫자를 입력해 주세요"); return }
    if (n < lo || n > hi) { setHint(`${lo}~${hi}% 사이로 입력해 주세요`); return }
    setHint("")
    onChange(Math.round(n * 10) / 1000)
  }
  const message = error ?? hint
  return (
    <div>
      <div className="mb-2 flex items-center gap-1"><label htmlFor={id} className="text-sm font-semibold text-slate-700">{label}</label>{info && <InfoTip label={label}>{info}</InfoTip>}</div>
      <div className="flex items-center gap-3">
        <input type="range" aria-label={`${label} 슬라이더`} className="min-w-0 flex-1 accent-blue-700" min={min} max={max} step={step} value={value} onChange={(e) => { setDraft(null); setHint(""); onChange(Number(e.target.value)) }} />
        <span className="relative w-24 shrink-0">
          <input id={id} type="number" inputMode="decimal" min={lo} max={hi} step={1} aria-invalid={!!message} className={`${inputClass} pr-8 text-right tabular-nums ${message ? "border-red-300" : ""}`} value={draft ?? String(round1(value))} onChange={(e) => type(e.target.value)} onBlur={() => { setDraft(null); setHint("") }} />
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-slate-400">%</span>
        </span>
      </div>
      <p className="mt-1 flex justify-between text-[11px] text-slate-400" aria-hidden="true"><span>{lo}%</span><span>{hi}%</span></p>
      {message ? <p className="mt-1 text-xs font-medium text-red-600">{message}</p> : help && <p className="mt-1 text-xs leading-5 text-slate-500">{help}</p>}
    </div>
  )
}

/** 여러 값을 칩으로 입력. Enter·쉼표로 추가하고, 칸을 벗어나면 적던 값도 추가한다. 한글 조합 중 Enter 는 무시한다. */
export function TagInput({ label, values, onChange, normalize = (s) => s.trim(), placeholder, info, help, error }: { label: string; values: string[]; onChange: (v: string[]) => void; normalize?: (s: string) => string; placeholder?: string; info?: React.ReactNode; help?: React.ReactNode; error?: string }) {
  const id = useId()
  const [text, setText] = useState("")
  const add = (raw: string) => {
    const items = raw.split(",").map(normalize).filter(Boolean)
    const next = [...values]
    for (const t of items) if (!next.includes(t)) next.push(t)
    if (next.length !== values.length) onChange(next)
  }
  const change = (s: string) => {
    if (!s.includes(",")) { setText(s); return }
    const parts = s.split(",")
    add(parts.slice(0, -1).join(","))
    setText(parts[parts.length - 1])
  }
  const key = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.nativeEvent.isComposing) return
    if (e.key === "Enter") { e.preventDefault(); add(text); setText("") }
    else if (e.key === "Backspace" && text === "" && values.length) onChange(values.slice(0, -1))
  }
  return (
    <div>
      <div className="mb-2 flex items-center gap-1"><label htmlFor={id} className="text-sm font-semibold text-slate-700">{label}</label>{info && <InfoTip label={label}>{info}</InfoTip>}</div>
      <div className={`flex flex-wrap items-center gap-1.5 rounded-xl border bg-white px-2 py-1.5 focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100 ${error ? "border-red-300" : "border-slate-200"}`}>
        {values.map((v) => (
          <span key={v} className="inline-flex items-center gap-1 rounded-lg bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-800">
            {v}
            <button type="button" aria-label={`${v} 삭제`} onClick={() => onChange(values.filter((x) => x !== v))} className="rounded p-0.5 hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-blue-500"><X className="size-3" /></button>
          </span>
        ))}
        <input id={id} className="min-w-28 flex-1 bg-transparent px-1.5 py-1 text-sm text-slate-900 outline-none placeholder:text-slate-400" value={text} placeholder={values.length ? "" : placeholder} onChange={(e) => change(e.target.value)} onKeyDown={key} onBlur={() => { if (text.trim()) { add(text); setText("") } }} />
      </div>
      {error ? <p className="mt-1.5 text-xs font-medium text-red-600">{error}</p> : help && <p className="mt-1.5 text-xs leading-5 text-slate-500">{help}</p>}
    </div>
  )
}

/** GICS 섹터 11개. 이름은 백엔드 종목 설명 자료(backend/data/processed/all_descriptor.json 의 gics.sector)와 같다.
 *  백엔드(m3_selection/retrieve.py)는 한국어 이름·영문 이름·2자리 코드를 모두 받는다. 새로 고를 때는 한국어 이름으로 저장한다. */
export const SECTORS: { code: string; ko: string; en: string }[] = [
  { code: "10", ko: "에너지", en: "Energy" }, { code: "15", ko: "소재", en: "Materials" }, { code: "20", ko: "산업재", en: "Industrials" },
  { code: "25", ko: "경기소비재", en: "Consumer Discretionary" }, { code: "30", ko: "필수소비재", en: "Consumer Staples" }, { code: "35", ko: "헬스케어", en: "Health Care" },
  { code: "40", ko: "금융", en: "Financials" }, { code: "45", ko: "정보기술", en: "Information Technology" }, { code: "50", ko: "커뮤니케이션 서비스", en: "Communication Services" },
  { code: "55", ko: "유틸리티", en: "Utilities" }, { code: "60", ko: "부동산", en: "Real Estate" },
]
const aliases = (s: (typeof SECTORS)[number]) => [s.ko, s.en, s.code]

/** 제외 섹터 다중 선택. 저장된 값이 영문 이름·코드여도 같은 섹터로 체크하고, 목록에 없는 값은 지우지 않고 따로 보여 준다. */
export function SectorPicker({ values, onChange }: { values: string[]; onChange: (v: string[]) => void }) {
  const known = new Set(SECTORS.flatMap(aliases))
  const unknown = values.filter((v) => !known.has(v))
  const toggle = (s: (typeof SECTORS)[number], on: boolean) => onChange(on ? [...values, s.ko] : values.filter((v) => !aliases(s).includes(v)))
  return (
    <fieldset>
      <legend className="mb-2 block text-sm font-semibold text-slate-700">제외할 섹터 <span className="font-normal text-slate-400">(여러 개 선택 가능)</span></legend>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {SECTORS.map((s) => {
          const on = values.some((v) => aliases(s).includes(v))
          return (
            <label key={s.code} className={`flex cursor-pointer items-center gap-2 rounded-xl border px-3 py-2 text-sm transition focus-within:ring-2 focus-within:ring-blue-500 ${on ? "border-blue-400 bg-blue-50 text-blue-900" : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"}`}>
              <input type="checkbox" className="accent-blue-700" checked={on} onChange={(e) => toggle(s, e.target.checked)} />
              <span className="min-w-0"><span className="block font-semibold">{s.ko}</span><span className="block truncate text-[11px] text-slate-400">{s.en}</span></span>
            </label>
          )
        })}
      </div>
      {unknown.length > 0 && (
        <div className="mt-2 rounded-xl bg-amber-50 p-3 text-xs leading-5 text-amber-900">
          목록에 없는 섹터 이름이 저장돼 있습니다. 분석에서는 인식하지 못해 무시될 수 있습니다:
          <span className="ml-1 inline-flex flex-wrap gap-1">{unknown.map((v) => <button key={v} type="button" aria-label={`${v} 삭제`} onClick={() => onChange(values.filter((x) => x !== v))} className="inline-flex items-center gap-1 rounded bg-white px-1.5 font-semibold hover:bg-amber-100">{v}<X className="size-3" /></button>)}</span>
        </div>
      )}
    </fieldset>
  )
}
