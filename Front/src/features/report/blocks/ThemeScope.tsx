/** 투자 테마의 「어떤 기업이 해당하는가」: 서버 글 「포함: … 넣지 않음: … (덧붙인 설명)」을 포함 / 넣지 않음 / 참고로 나눠 보여 준다
 *  (2026-11-16 사용자 요청: 한 문단 안에 두 내용이 같이 있어 구분이 안 됨). 틀이 다르면 null → 부르는 쪽이 원문 그대로. */
export interface ThemeScopeParts { include: string | null; exclude: string | null; note: string | null }

export function splitThemeScope(text: string): ThemeScopeParts | null {
  const t = text.trim()
  const m = /^포함\s*:\s*([\s\S]*?)\s*(?:넣지 않음\s*:\s*([\s\S]*))?$/.exec(t)
  if (!m || !m[1]) return null
  let exclude = m[2]?.trim() || null
  let note: string | null = null
  if (exclude) {  // 넣지 않음 목록은 첫 문장까지, 그 뒤 문장은 덧붙인 설명 (예: '업종이 다르다는 사실만으로 … 보장되지는 않습니다')
    const s = /^(.+?[.。])\s+(\S[\s\S]*)$/.exec(exclude)
    if (s) { exclude = s[1].trim(); note = s[2].trim() }
  } else {
    const s = /^(.+?[.。])\s+(\S[\s\S]*)$/.exec(m[1].trim())
    if (s) return { include: s[1].trim(), exclude: null, note: s[2].trim() }
  }
  return { include: m[1].trim(), exclude, note }
}

/** size: 표 칸은 sm, 카드는 xs. */
export function ThemeScope({ text, size = "sm" }: { text: string; size?: "sm" | "xs" }) {
  const p = splitThemeScope(text)
  const body = size === "sm" ? "text-sm leading-6" : "text-xs leading-5"
  if (!p) return <span className={body}>{text}</span>
  // 넓은 화면: 이름표 칸 + 글(내어쓰기), 좁은 화면: 이름표를 글 앞에 붙이고 글은 아래로 이어서 (좁은 표 칸에서도 잘리지 않게)
  const tag = "mr-1.5 inline-flex shrink-0 justify-center rounded-md px-1.5 py-0.5 align-[1px] text-[11px] font-semibold leading-4 sm:mr-0 sm:mt-0.5 sm:w-[4.25rem]"
  const row = "sm:flex sm:items-start sm:gap-2"
  return (
    <dl className="space-y-1.5">
      {p.include && <div className={row}><dt className={`${tag} bg-emerald-50 text-emerald-800 ring-1 ring-inset ring-emerald-200`}>포함</dt><dd className={`${body} inline min-w-0 text-slate-700 sm:block`}>{p.include}</dd></div>}
      {p.exclude && <div className={row}><dt className={`${tag} bg-slate-100 text-slate-700 ring-1 ring-inset ring-slate-300`}>넣지 않음</dt><dd className={`${body} inline min-w-0 text-slate-700 sm:block`}>{p.exclude}</dd></div>}
      {p.note && <div><dt className="sr-only">참고</dt><dd className={`${size === "sm" ? "text-xs leading-5" : "text-[11px] leading-4"} min-w-0 text-slate-500 sm:pl-[calc(4.25rem+0.5rem)]`}>{p.note}</dd></div>}
    </dl>
  )
}
