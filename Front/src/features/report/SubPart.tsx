import { HelpTip } from "./terms"

/** 리포트 섹션 안의 「큰 파트」 (2026-11-14 사용자 요청: 3. 포트폴리오 구성의 모양을 모든 섹션에 맞춘다).
 *  큰 제목(18px) + 시점·상태 표시, 그 아래 작은 파트들은 왼쪽 세로선 안에 들여 써서 이 파트에 속한다는 것이 보이게.
 *  번호는 붙이지 않는다 (2026-11-14 사용자 요청).
 *  작은 파트 제목은 16px 굵게(블록 제목·접이식 제목과 같은 크기). */
export function SubPart({ id, title, desc, info, badge, when, children }: { id?: string; title: string; desc?: React.ReactNode; info?: React.ReactNode; badge?: React.ReactNode; when?: string; children: React.ReactNode }) {
  return (
    <section id={id} aria-label={title} className="scroll-mt-16 space-y-4 border-t border-slate-200 pt-7 first:border-t-0 first:pt-0">
      <div>
        <h3 className="flex flex-wrap items-center gap-x-2 gap-y-1 text-lg font-bold leading-6 text-slate-950">{title}{info && <HelpTip label={title}>{info}</HelpTip>}{badge}{when && <span className="rounded-full border border-slate-300 bg-white px-2 py-0.5 text-[11px] font-semibold text-slate-600">{when}</span>}</h3>
        {desc && <div className="mt-1 text-xs leading-5 text-slate-500">{desc}</div>}
      </div>
      <div className="space-y-4 border-l-2 border-slate-200 pl-3 sm:pl-6">{children}</div>
    </section>
  )
}
