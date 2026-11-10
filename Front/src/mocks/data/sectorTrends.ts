// 홈 '요즘엔 뭐가 좋아요?' 목업 자료. 숫자는 2026-11-11 실제 DB 로 서버 규칙(m2_data/sector_trends.py)을 돌린 결과를 목업 기준일에 옮긴 것이다.
// 성향별 추천(picks)도 서버와 같은 규칙으로 여기서 만든다: 상자에 보이는 섹터(top) 중 안정형·안정추구형 = 변동성 최소,
// 위험중립형 = 수익률÷변동성 최대, 적극·공격투자형 = 수익률 최대.
import type { ProposedSectorMarket, ProposedSectorPick, ProposedSectorScope, ProposedSectorTrendsData } from "../../api/proposed"
import type { Tendency } from "../../api/types"
import { MOCK_AS_OF } from "../scenarios"

type Row = [code: string, name: string, n: number, up: number, avg: number, vol: number, leaders?: [string, string, number][]]

const prompt = (market: string, name: string) => `요즘 많이 오른 ${market} ${name} 기업에 나눠 투자하고 싶어요.`

function market(code: "US" | "KR", label: string, avg: number, bench: [string, string, number], rows: Row[]): ProposedSectorMarket {
  const sectors = rows.map(([c, name, n, up, r, vol, leaders = []]) => ({
    code: c, name_ko: name, n, up, avg_return: r, vol_3m: vol,
    good: n >= 5 && r > 0 && r > avg && up / n >= 0.5,
    leaders: leaders.map(([ticker, nm, x]) => ({ ticker, name: nm, return: x })), prompt_ko: prompt(label, name),
  }))
  return { code, label_ko: label, base_date: "2026-09-30", end_date: MOCK_AS_OF, n: sectors.reduce((s, x) => s + x.n, 0), avg_return: avg,
    benchmark: { ticker: bench[0], label_ko: bench[1], return: bench[2] }, sectors, top: sectors.filter((s) => s.good).slice(0, 3).map((s) => s.code) }
}

const MARKETS: ProposedSectorMarket[] = [
  market("US", "미국", 0.0349, ["SPY", "S&P 500", -0.0331], [
    ["25", "경기소비재", 49, 41, 0.106, 0.2227, [["HAS", "Hasbro", 0.30], ["LOW", "Lowe's", 0.25], ["BBY", "Best Buy", 0.22]]],
    ["30", "필수소비재", 33, 30, 0.099, 0.1948, [["CLX", "Clorox", 0.26], ["STZ", "Constellation Brands", 0.19], ["HRL", "Hormel Foods", 0.18]]],
    ["35", "헬스케어", 61, 56, 0.095, 0.1921, [["IDXX", "Idexx Laboratories", 0.37], ["GEHC", "GE HealthCare", 0.28], ["REGN", "Regeneron Pharmaceuticals", 0.23]]],
    ["60", "부동산", 30, 29, 0.074, 0.1672],
    ["15", "소재", 25, 18, 0.073, 0.1814],
    ["40", "금융", 76, 64, 0.071, 0.1668],
    ["55", "유틸리티", 31, 25, 0.058, 0.1513],
    ["20", "산업재", 87, 56, 0.047, 0.1641],
    ["50", "커뮤니케이션 서비스", 21, 12, 0.028, 0.2027],
    ["10", "에너지", 21, 3, -0.067, 0.2419],
    ["45", "정보기술", 81, 24, -0.133, 0.3231],
  ]),
  market("KR", "한국", -0.1363, ["069500.KS", "코스피 200", -0.2571], [
    ["60", "부동산", 1, 1, 0.592, 0.781],
    ["35", "헬스케어", 14, 9, 0.045, 0.3404, [["207940", "삼성바이오로직스", 0.24], ["326030", "SK바이오팜", 0.19], ["068270", "셀트리온", 0.17]]],
    ["50", "커뮤니케이션 서비스", 11, 6, 0.001, 0.2271, [["259960", "크래프톤", 0.16], ["032640", "LG유플러스", 0.11], ["030000", "제일기획", 0.04]]],
    ["55", "유틸리티", 3, 2, -0.006, 0.2343],
    ["30", "필수소비재", 22, 11, -0.025, 0.2561],
    ["25", "경기소비재", 25, 4, -0.103, 0.2509],
    ["40", "금융", 22, 3, -0.119, 0.2464],
    ["15", "소재", 33, 3, -0.18, 0.3223],
    ["20", "산업재", 51, 4, -0.228, 0.3753],
    ["45", "정보기술", 16, 2, -0.268, 0.4781],
    ["10", "에너지", 3, 0, -0.347, 0.5817],
  ]),
]

const TENDENCIES: Tendency[] = ["안정형", "안정추구형", "위험중립형", "적극투자형", "공격투자형"]
const RULE: Record<Tendency, ProposedSectorPick["rule"]> = { 안정형: "low_vol", 안정추구형: "low_vol", 위험중립형: "ratio", 적극투자형: "top", 공격투자형: "top" }
const TAIL: Record<ProposedSectorPick["rule"], string> = {
  low_vol: "성과가 좋았던 섹터 중 최근 3개월 주가 오르내림이 가장 작았습니다.",
  ratio: "주가 오르내림에 비해 오른 폭이 가장 컸습니다.",
  top: "성과가 좋았던 섹터 중 가장 많이 올랐습니다.",
}
const pctText = (x: number) => `${x > 0 ? "+" : ""}${(x * 100).toFixed(2)}%`

function pick(t: Tendency, markets: ProposedSectorMarket[]): ProposedSectorPick {
  const rule = RULE[t]
  const cands = markets.flatMap((m) => m.sectors.filter((s) => m.top.includes(s.code) && (rule === "top" || s.vol_3m)).map((s) => ({ m, s })))
  const score = (c: (typeof cands)[number]) => (rule === "low_vol" ? -(c.s.vol_3m ?? 0) : rule === "ratio" ? c.s.avg_return / (c.s.vol_3m ?? 1) : c.s.avg_return)
  const best = cands.reduce<(typeof cands)[number] | null>((b, c) => (b === null || score(c) > score(b) ? c : b), null)
  if (!best) return { tendency: t, rule, market: null, code: null, name_ko: null, avg_return: null, text_ko: "최근 한 달은 시장 평균보다 많이 오른 섹터가 없습니다." }
  return { tendency: t, rule, market: best.m.code, code: best.s.code, name_ko: best.s.name_ko, avg_return: best.s.avg_return,
    text_ko: `${t}에 맞는 섹터는 ${best.m.label_ko} ${best.s.name_ko}입니다. 최근 한 달 ${pctText(best.s.avg_return)} 올랐고, ${TAIL[rule]}` }
}

const scopes: ProposedSectorScope[] = ["US", "KR", "ALL"]

export const SECTOR_TRENDS: ProposedSectorTrendsData = {
  rule_version: "sector-trends-v1", as_of: MOCK_AS_OF, computed_at: `${MOCK_AS_OF}T08:00:00+09:00`, markets: MARKETS,
  picks: Object.fromEntries(scopes.map((sc) => [sc, Object.fromEntries(TENDENCIES.map((t) => [t, pick(t, MARKETS.filter((m) => sc === "ALL" || m.code === sc))]))])) as ProposedSectorTrendsData["picks"],
}
