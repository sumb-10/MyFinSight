import { navigate } from "../../app/router"
import { Button, EmptyState } from "../../ui"
import { Example0 } from "./Example0"
import { Example1 } from "./Example1"
import { Example2 } from "./Example2"
import { Example3 } from "./Example3"
import { Example3Prev } from "./Example3Prev"
import { Example4 } from "./Example4"
import type { ExampleRoute, ExampleVersion } from "./shared"

/**
 * 홈 화면 시안(예시 페이지) 고르기: #/home/0, #/home/1 … (이 폴더의 README.md 참고)
 * 3 번은 「이렇게 진행돼요」 탭을 넣기 전 모습을 「이전 버전」(주소 ?prev=1, ExampleNPrev.tsx)으로 남겨 두고 전환 막대에서 바로 비교한다.
 */
export function HomeExample({ route }: { route: ExampleRoute }) {
  const prev = !!route.prev
  // 구성·색 같은 다른 주소 값은 그대로 두고 버전만 바꾼다
  const version: ExampleVersion = { prev, go: (p) => { const { prev: _drop, ...rest } = route; void _drop; navigate(p ? { ...rest, prev: true } : rest, { scroll: false }) } }
  const layout = route.layout ?? "a"
  const color = route.color ?? "mix"
  switch (route.n) {
    case 0: return <Example0 color={color} bare={route.bare} />
    case 1: return <Example1 color={color} bare={route.bare} />
    case 2: return <Example2 bare={route.bare} />
    case 3: return prev ? <Example3Prev bare={route.bare} version={version} /> : <Example3 layout={layout} bare={route.bare} version={version} />
    case 4: return <Example4 layout={layout} color={color} bare={route.bare} />
    default: return <EmptyState title="없는 시안입니다" description={`홈 시안 ${route.n}번은 없습니다.`} action={<Button onClick={() => navigate({ page: "home" })}>홈으로</Button>} />
  }
}
