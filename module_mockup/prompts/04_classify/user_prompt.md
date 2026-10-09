아래 테마 정의를 기준으로 후보 종목을 분류하세요. (배치 {{batch_index}}/{{batch_total}}, {{batch_size}}종목)

## 테마

{{themes_block}}

## 제외 테마 (해당 시 excluded_theme 에 표기)

{{exclude_block}}

## 후보 종목 (ticker | name | GICS sub-industry | summary)

```
{{candidates_block}}
```

## 지시

목록의 모든 종목에 대해 `{ticker, in_theme, themes, confidence, reason_ko, excluded_theme}` 를 판정하고, 스키마를 따르는 JSON 객체 하나만 출력하세요.
