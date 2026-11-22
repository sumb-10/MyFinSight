// 「연결 설정」 화면 (사이드바 아래 입구, #/settings). 연결 하나가 한 줄이고, 「연결하기」·「바꾸기」를 누르면 그 줄이 처음 설정과 같은 입력칸으로 펼쳐진다.
// 팝업이 아니라 제 화면으로 둔다: 비밀 값을 받는 화면이라 주소가 있는 화면이 더 믿을 만하고, 닫혀서 입력을 잃을 일이 없다.
import { useEffect, useState } from "react"
import { Database, Loader2 } from "lucide-react"
import { errorMessage } from "../../api/client"
import type { ProposedConnectionKind, ProposedConnections } from "../../api/proposed"
import { useHealth, useService } from "../../app/providers"
import { Button, ErrorState, Loading, NOTICE_BOX } from "../../ui"
import { MockTag } from "../report/proposedView"
import { dataStarts } from "./copy"
import { OpenAiMark } from "./openaiMark"
import { ErrorNote, SecretField, StateChip, useConnect } from "./parts"

const ROWS = {
  database: { title: "팀 DB", icon: Database, label: "팀에서 받은 DB 접속 주소", placeholder: "postgresql://계정:비밀번호@서버:5432/이름", empty: "팀에서 받은 접속 주소", clearAsk: "저장한 주소를 지울까요? 지우면 예시 데이터로 돌아갑니다." },
  llm: { title: "분석 모델", icon: OpenAiMark, label: "OpenAI API 키", placeholder: "팀에서 받은 키 또는 직접 만든 키", empty: "OpenAI API 키", clearAsk: "저장한 키를 지울까요? 지우면 미리 만든 답으로 돌아갑니다." },
} as const

export function ConnectionSettings() {
  const svc = useService()
  const [conns, setConns] = useState<ProposedConnections | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const load = () => { setLoadError(null); svc.getConnections!().then(setConns, (e) => setLoadError(errorMessage(e))) }
  useEffect(load, [svc])  // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="connect max-w-[760px]">
      <div className="flex items-center"><h1 className="t-display">연결 설정</h1><MockTag /></div>
      {loadError ? <div className="mt-6"><ErrorState title="연결 상태를 불러오지 못했습니다" message={loadError} retry={load} /></div>
        : !conns ? <Loading />
        : (
          <>
            <div className="mt-6 divide-y divide-line rounded-card bg-surface">
              <Row kind="database" conns={conns} onChange={setConns} detail={conns.database.latest_trading_day ? [`최신 거래일 ${conns.database.latest_trading_day}`, starts(conns.database)].filter(Boolean) : []} />
              <Row kind="llm" conns={conns} onChange={setConns} detail={[]} />
            </div>
            {/* 저장하는 곳을 사실대로: 운영체제 보관함 이름, 보관함이 없는 환경(Docker)이면 환경변수로 연결한다는 것 */}
            <p className="mx-1 mt-3.5 text-13 text-sub">{conns.can_save ? `주소와 키는 ${conns.store_label_ko ?? "이 컴퓨터의 보관함"}에 저장되고 여기서 지울 수 있습니다.` : "이 환경에서는 화면에서 저장할 수 없습니다. 서버의 .env 파일에 적은 값으로 연결합니다."}</p>
          </>
        )}
    </div>
  )
}

/** 「자료 시작일 미국 1993-01-29, 한국 2002-10-14」 — 시장마다 자료가 시작하는 날이 다르다. 최신 거래일 아래 줄에 따로 둔다 */
function starts(db: ProposedConnections["database"]): string {
  const list = dataStarts(db).map((s) => (s.market ? `${s.market} ${s.date}` : s.date))
  return list.length ? `자료 시작일 ${list.join(", ")}` : ""
}

function Row({ kind, conns, onChange, detail }: { kind: ProposedConnectionKind; conns: ProposedConnections; onChange: (c: ProposedConnections) => void; detail: string[] }) {
  const svc = useService()
  const { reload } = useHealth()
  const r = ROWS[kind], conn = conns[kind]
  const fromEnv = conn.source === "env"         // 환경변수(.env · Docker Compose)로 들어온 연결: 보여 주기만 한다
  const problem = kind === "database" && !conn.connected ? conns.database.error : null  // 주소는 있는데 닿지 않는다
  const pinned = kind === "llm" && conns.llm.stub_pinned                                 // 서버가 연습 모드로 고정 (MYFINSIGHT_LLM=stub)
  const [open, setOpen] = useState(false)       // 입력칸 펼침
  const [asking, setAsking] = useState(false)   // 지우기 확인
  const [value, setValue] = useState("")
  const [clearError, setClearError] = useState<string | null>(null)
  const c = useConnect(kind, (cs) => { onChange(cs); close() })
  const busy = c.phase === "testing"
  function close() { setOpen(false); setValue(""); c.dismiss() }
  const clear = async () => {
    setClearError(null)
    try { onChange(await svc.clearConnection!(kind)); setAsking(false); reload() } catch (e) { setClearError(errorMessage(e)) }
  }
  return (
    <section aria-label={r.title} className="grid grid-cols-[40px_1fr_auto_auto] items-center gap-x-4 gap-y-1 px-6 py-[22px]">
      <r.icon className="size-7 justify-self-center text-main" aria-hidden="true" />
      <div className="min-w-0">
        <h2 className="text-[16px] font-bold leading-6 text-main">{r.title}</h2>
        {conn.connected || fromEnv
          ? <>{conn.masked && <p className="truncate font-mono text-12 text-sub">{conn.masked}</p>}{conn.connected && detail.map((line) => <p key={line} className="text-13 text-sub">{line}</p>)}{fromEnv && <p className="text-13 text-sub">환경변수(.env)로 설정됨</p>}</>
          : <p className="text-13 text-sub">{conns.can_save ? r.empty : `${r.empty} · 서버의 .env 파일로 넣습니다`}</p>}
      </div>
      <StateChip connected={conn.connected} />
      {/* 환경변수로 들어온 연결과 저장할 수 없는 환경에서는 버튼을 두지 않는다 (눌러도 서버가 거절한다).
          펼쳐 둔 동안에도 줄의 버튼을 숨긴다 (아래 「연결하기」와 겹치지 않게) */}
      <div className="flex items-center gap-1">
        {!open && !asking && !fromEnv && !pinned && conns.can_save && (conn.connected
          ? <><Button variant="soft" className="bg-sunken!" onClick={() => setOpen(true)}>바꾸기</Button><button type="button" onClick={() => setAsking(true)} className="h-10 rounded-control px-3 text-14 font-semibold text-sub transition hover:bg-danger-tint hover:text-danger focus:outline-none focus-visible:ring-2 focus-visible:ring-focus">지우기</button></>
          : <Button onClick={() => setOpen(true)}>연결하기</Button>)}
      </div>
      {/* 연결되지 않은 까닭이 서버 쪽에 있을 때: 닿지 않는 주소(환경변수) · 연습 모드로 고정. 화면에서 고칠 수 없으니 원인과 푸는 방법을 적는다 */}
      {(problem || pinned) && <div className="col-start-2 col-end-[-1] -mx-5"><ErrorNote error={problem ?? { code: "stub_pinned", value: null, raw: null }} /></div>}
      {open && (
        <div className="col-start-2 col-end-[-1] mt-3">
          <SecretField icon={r.icon} label={r.label} value={value} onChange={(v) => { setValue(v); c.dismiss() }} placeholder={r.placeholder} invalid={c.phase === "error"} busy={busy} describedBy={`settings-${kind}-error`} autoFocus />
          {c.error && <ErrorNote id={`settings-${kind}-error`} error={c.error} />}
          <div className="mt-3.5 flex justify-end gap-2">
            <Button variant="soft" className="bg-sunken!" onClick={busy ? c.cancel : close}>취소</Button>
            <Button disabled={busy || value.trim() === ""} onClick={() => void c.submit(value.trim())}>{busy ? <><Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />연결을 확인하는 중…</> : c.phase === "error" ? "다시 연결하기" : "연결하기"}</Button>
          </div>
        </div>
      )}
      {asking && (
        <div role="alertdialog" aria-label={`${r.title} 지우기 확인`} className={`col-start-2 col-end-[-1] mt-3 rounded-box p-4 text-14 leading-6 text-body ${NOTICE_BOX.error}`}>
          <p className="font-semibold text-main">{r.clearAsk}</p>
          {clearError && <p className="mt-1 text-danger">{clearError}</p>}
          <div className="mt-3 flex gap-2">
            <Button variant="destructive" onClick={() => void clear()}>지우기</Button>
            <Button variant="soft" onClick={() => { setAsking(false); setClearError(null) }}>취소</Button>
          </div>
        </div>
      )}
    </section>
  )
}
