기준일 {{as_of}} 시점에서 아래 종목과 **뉴스 근거**를 바탕으로 뷰 세트를 생성하세요.

## 사용자 의도

{{summary_ko}}

테마:
{{themes_block}}

## 종목 (ticker | name | sector | 한 줄 소개 | 직전 12개월 수익률 | 연변동성 | 시총비중 | 베이스라인 비중 | implied_return)

```
{{stocks_block}}
```

## 뉴스 근거 — 기준일 이전 {{news_window_days}}일 헤드라인 (id | 날짜 | 출처(origin) | 발행사 | ticker | 제목)

```
{{evidence_block}}
```

근거가 없는 종목: {{no_news_tickers}}

## 조건

- 세트 수: {{n_sets}}, 세트당 뷰 수: {{views_per_set}} (absolute ≥ 1, relative ≥ 1)
- confidence 범위: 0.1 ~ {{max_conf}}
- 절대 뷰 수익률 범위 {{abs_range}}, 상대 뷰 아웃퍼폼 범위 {{rel_range}} (연율)
- 모든 뷰는 `evidence_ids` 를 1개 이상 인용

스키마를 따르는 JSON 객체 하나만 출력하세요.
