import { useService } from "../../app/providers"
import { useResource } from "../../state/useResource"
import { HomeScreen } from "../home/HomeScreen"
import { ClarifyScreen } from "./ClarifyScreen"

/**
 * 질문 단계 주소(#/analysis/:id). 홈에서 시작한 새 분석(mode "new")은 홈 화면의 대화창에서 질문에 답하고,
 * 리포트에서 시작한 재분석(rerun)·수정 요청(revision)은 원안 비교 카드 등이 있는 기존 질문 화면을 그대로 쓴다.
 * 요청을 읽는 동안에는 새 분석이라고 보고 홈 대화창(불러오는 중 표시)부터 그린다 → 홈에서 넘어올 때 화면이 깜빡이지 않는다.
 */
export function ClarifyRoute({ requestId }: { requestId: string }) {
  const svc = useService()
  const res = useResource(() => svc.getRequest(requestId), [svc, requestId])
  // 이 주소는 홈처럼 넓은 틀(App.tsx)이라, 기존 질문 화면은 다른 화면과 같은 폭(1100px)으로 좁혀 그린다
  if (res.data && res.data.mode !== "new") return <div className="mx-auto max-w-[1100px]"><ClarifyScreen requestId={requestId} /></div>
  return <HomeScreen request={{ id: requestId, res }} />
}
