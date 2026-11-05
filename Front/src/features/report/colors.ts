import { OTHER_COLOR } from "../../lib/format"

/** 종목(티커) 색: 리포트의 종목 비중 표시(투자 금액 카드·배분 도넛)에만 쓴다. 브랜드 파랑에서 시작하는 차분한 8색이고,
 *  비중 순서대로 붙으므로 이웃한 색끼리 색각 이상에서도 구분되도록 순서를 정했다 (dataviz validate_palette: 인접 CVD ΔE ≥ 15.9, 일반 ΔE ≥ 19.4).
 *  밝은 두 색(호박·하늘)은 흰 바탕 대비가 3:1 미만이라 항상 종목 이름·비중 글자와 함께 쓴다. 전략 계열 선 차트는 lib/format 의 PALETTE 그대로. */
export const HOLDING_PALETTE = ["#2563eb", "#22a69a", "#5b3fc4", "#d9709b", "#e2a33e", "#2e7d4f", "#79b4ee", "#b85a2e"]

/** 같은 종목은 같은 색: 비중 순 목록 안의 위치로 정한다. 9번째부터는 새 색을 만들지 않고 회색(기타)으로. */
export const holdingColor = (id: string, ids: string[]) => { const i = ids.indexOf(id); return i < 0 || i >= HOLDING_PALETTE.length ? OTHER_COLOR : HOLDING_PALETTE[i] }
