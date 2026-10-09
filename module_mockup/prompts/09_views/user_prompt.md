기준일 {{as_of}} 시점에서 아래 포트폴리오 종목에 대한 뷰 세트를 생성하세요.

## 사용자 의도

{{summary_ko}}

테마:
{{themes_block}}

## 종목 (ticker | name | sector | 한 줄 소개 | 직전 12개월 수익률 | 연변동성 | 시총비중 | 베이스라인 비중 | implied_return)

```
{{stocks_block}}
```

## 조건

- 세트 수: {{n_sets}}, 세트당 뷰 수: {{views_per_set}} (absolute ≥ 1, relative ≥ 1)
- confidence 범위: 0.1 ~ {{max_conf}}
- 절대 뷰 수익률 범위 {{abs_range}}, 상대 뷰 아웃퍼폼 범위 {{rel_range}} (연율)

스키마를 따르는 JSON 객체 하나만 출력하세요.
