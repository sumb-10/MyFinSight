import { useId, useState } from "react"
import { ChevronDown } from "lucide-react"
import { InfoTip } from "./inputs"

// 내 투자조건 화면(저장·수정)의 파트 카드. 옅은 회색 페이지 위의 흰 카드, 제목 영역은 옅은 배경과 구분선으로 본문과 나눈다.
// 파란색은 현재 단계·선택한 옵션에만 쓰고, 여기 제목·배지는 회색 계열로 둔다. 공통 Card/Disclosure 는 다른 화면이 쓰므로 건드리지 않는다.

export type PartTag = "필수" | "선택" | "고급"

export function Tag({ tag }: { tag: PartTag }) {
  return <span className={`inline-flex shrink-0 items-center rounded-md border px-1.5 py-0.5 text-[11px] font-semibold ${tag === "필수" ? "border-slate-400 bg-white text-slate-700" : "border-slate-200 bg-slate-100 text-slate-500"}`}>{tag}</span>
}

/** 파트 제목 + ⓘ + 필수/선택 표시. */
export function GroupTitle({ title, info, tag }: { title: string; info?: React.ReactNode; tag?: PartTag }) {
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-base font-bold text-slate-950">
      <span className="inline-flex items-center gap-1">{title}{info && <InfoTip label={title}>{info}</InfoTip>}</span>
      {tag && <Tag tag={tag} />}
    </span>
  )
}

const shell = "rounded-2xl border border-slate-300 bg-white shadow-sm"
const headBar = "border-b border-slate-200 bg-slate-50 px-5 py-4 sm:px-6"

/** 파트 카드: 제목 영역(제목·짧은 설명·오른쪽 조작) + 본문. */
export function Part({ title, info, tag, desc, aside, children }: { title: string; info?: React.ReactNode; tag?: PartTag; desc?: React.ReactNode; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className={shell}>
      <header className={`flex items-center justify-between gap-4 rounded-t-2xl ${headBar}`}>
        <div className="min-w-0">
          <h3><GroupTitle title={title} info={info} tag={tag} /></h3>
          {desc && <p className="mt-1 text-xs leading-5 text-slate-500">{desc}</p>}
        </div>
        {aside}
      </header>
      <div className="space-y-4 p-5 sm:p-6">{children}</div>
    </section>
  )
}

/** 접히는 파트 카드. 접혀 있어도 제목 줄에 요약을 보여 준다. open 을 주면 바깥에서 제어 (예: 오류가 있으면 펼침). */
export function PartDisclosure({ title, tag, summary, open: openProp, onToggle, defaultOpen = false, children }: { title: string; tag?: PartTag; summary?: React.ReactNode; open?: boolean; onToggle?: (open: boolean) => void; defaultOpen?: boolean; children: React.ReactNode }) {
  const [own, setOwn] = useState(defaultOpen)
  const open = openProp ?? own
  const id = useId()
  const toggle = () => { if (openProp === undefined) setOwn(!open); onToggle?.(!open) }
  return (
    <section className={shell}>
      <button type="button" aria-expanded={open} aria-controls={id} onClick={toggle} className={`flex w-full items-center justify-between gap-4 text-left transition hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500 ${open ? "rounded-t-2xl" : "rounded-2xl"} ${headBar} ${open ? "" : "border-b-0"}`}>
        <span className="min-w-0"><GroupTitle title={title} tag={tag} /></span>
        <span className="flex min-w-0 shrink items-center gap-3 text-xs font-normal text-slate-500">{summary && <span className="hidden truncate sm:inline">{summary}</span>}<ChevronDown className={`size-4 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} /></span>
      </button>
      <div id={id} hidden={!open} className="space-y-4 p-5 sm:p-6">{open ? children : null}</div>
    </section>
  )
}
