아래 사용자 투자 요청과 GICS 분류 트리를 바탕으로 의도 명세 JSON을 생성하세요.

## user_request

주석(`//`)은 각 항목의 의미와 [HARD]/[SOFT] 구분을 설명합니다. 값만 데이터이며 주석은 출력에 포함하지 않습니다.

```jsonc
{{user_request_jsonc}}
```

## 이전 실행 맥락 (M1-03)

{{context}}

## 지금까지의 보충 질문과 답 (이미 요청에 반영됨)

{{dialog_history}}

이미 물어본 필드: {{asked_fields}} / 질문 상한: {{max_questions}}개

## 파생 값 (코드가 계산)

- as_of (포트폴리오 구성 기준일): {{as_of}}
- 투자금 (USD 환산): {{initial_amount_usd}}

## GICS 분류 트리 (코드 이름 (유니버스 내 종목 수))

```
{{gics_tree}}
```

## 지시

1. `natural_language.idea` 에서 테마를 추출하고, 각 테마에 해당하는 GICS 코드(넉넉하게)와 검색 키워드(구체적으로)를 적으세요.
2. `constraints.exclude_themes` 각각을 GICS 코드·키워드 규칙으로 번역하세요.
3. `[HARD]` 항목은 그대로 옮기고, `[SOFT]` 항목은 해석 지침대로 파라미터로 변환하세요.
4. 부족·모호·충돌·선호 확인이 필요한 항목이 있으면 `questions` 로 제안하세요 (없으면 빈 배열).
5. 스키마를 따르는 JSON 객체 하나만 출력하세요.
