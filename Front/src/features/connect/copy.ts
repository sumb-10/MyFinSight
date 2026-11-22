// 연결 실패 문구: 원인 한 줄 + 확인할 것 한 줄. 서버는 원인 코드만 주고 문구는 여기서 고른다.
// 원인에 맞는 것만 말한다 (주소를 못 찾았는데 비밀번호를 확인하라고 하지 않는다).
// 값은 조사 없이 콜론 뒤에 둔다 — 값에 따라 을/를을 고를 수 없어서 (「서버 주소를 찾지 못했습니다: db.example.com」).
import type { ProposedConnectionError, ProposedConnectionErrorCode, ProposedConnections } from "../../api/proposed"

const COPY: Record<ProposedConnectionErrorCode, { title: string; fix: string | null }> = {
  host_not_found: { title: "서버 주소를 찾지 못했습니다", fix: "주소에 오타가 없는지, 인터넷에 연결돼 있는지 확인해 주세요." },
  no_response: { title: "서버가 응답하지 않습니다", fix: "포트 번호가 맞는지, 접속이 허용된 네트워크인지 확인해 주세요." },
  auth_failed: { title: "계정이나 비밀번호가 맞지 않습니다", fix: "받은 주소를 다시 붙여 넣어 주세요." },
  database_not_found: { title: "이 이름의 데이터베이스가 없습니다", fix: "주소 끝의 이름을 확인해 주세요." },
  invalid_key: { title: "키가 올바르지 않습니다", fix: "키를 끝까지 복사했는지 확인해 주세요." },
  quota: { title: "이 키로는 지금 요청할 수 없습니다", fix: "OpenAI 계정의 결제 수단과 사용 한도를 확인해 주세요." },
  stub_pinned: { title: "서버가 연습 모드로 고정돼 있습니다", fix: ".env 파일에서 MYFINSIGHT_LLM=stub 줄을 지우고 서버를 다시 켜 주세요." },
  unknown: { title: "연결하지 못했습니다", fix: null },
}

export interface ErrorCopy { title: string; value: string | null; fix: string | null; raw: string | null }

export function errorCopy(e: ProposedConnectionError): ErrorCopy {
  const c = COPY[e.code] ?? COPY.unknown  // 서버가 새 코드를 보내도 화면은 그대로 동작한다
  return { title: c.title, value: e.value, fix: c.fix, raw: e.raw }
}

/** 분석 한 번의 사용료 어림을 화면 글자로 (유효 숫자 한 자리): 0.1 → "0.1", 0.091 → "0.09", 0.46 → "0.5", 1.2 → "1". 달러 기호 대신 뒤에 「달러」를 붙여 쓴다. */
const MARKET_KO: Record<string, string> = { US: "미국", KR: "한국" }
/** 자료 시작일을 시장별로: [{ market: "미국", date }, { market: "한국", date }]. 서버가 시장별 값을 주지 않으면 합친 날짜 하나 (market 없음). */
export function dataStarts(db: ProposedConnections["database"]): { market: string | null; date: string }[] {
  const by = Object.entries(db.data_start_by_market ?? {})
  if (by.length) return by.map(([m, date]) => ({ market: MARKET_KO[m] ?? m, date }))
  return db.data_start ? [{ market: null, date: db.data_start }] : []
}

export function costLabel(usd: number): string {
  return String(Number(usd.toPrecision(1)))
}
