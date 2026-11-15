import { navigate } from "../../app/router"
import { HomeScreen } from "../home/HomeScreen"
import { ExampleSwitch, SwitchGroup, useExampleTheme } from "./shared"
import "./toss.css"
import "./example0.css"

/**
 * 홈 시안 0 (#/home/0): 기존 홈 화면(HomeScreen)을 그대로 그리고 톤만 바꾼다 (배경 #F2F5F7 · 테두리 없는 흰 카드). 글꼴·굵기는 기존 그대로.
 * 구성·문구·동작은 기존 홈과 완전히 같다 (입력 초안 저장, 둘러보기 포함). color: toss.css 의 색 조합 (주소 ?color=all).
 */
export function Example0({ color, bare }: { color: "mix" | "all"; bare?: boolean }) {
  useExampleTheme("toss", color)
  return (
    <div className={`home-example-0 ${bare ? "" : "pb-10"}`}>
      <HomeScreen />
      {!bare && (
        <ExampleSwitch n={0}>
          <SwitchGroup label="색" items={[
            { label: "버튼 진한 파랑", on: color === "mix", go: () => navigate({ page: "home-example", n: 0 }, { scroll: false }) },
            { label: "전부 #4880EE", on: color === "all", go: () => navigate({ page: "home-example", n: 0, color: "all" }, { scroll: false }) },
          ]} />
        </ExampleSwitch>
      )}
    </div>
  )
}
