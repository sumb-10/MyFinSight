"""M4-03 뉴스 근거 뷰 생성기 (LLM #4). 구성일 직전 뉴스 창의 헤드라인만 근거로 BL 뷰를 만든다 (K6: 플레이스홀더 뷰 없음).

LLM 은 뷰의 방향(up/down)과 강도(weak/medium/strong)만 낸다. 수치 Q 는 코드가 사전 기대수익 π 대비로 만든다
(2026-11 시나리오 QA, 논의사항 C1: LLM 이 "좋은 소식 +3%" 처럼 π 보다 낮은 숫자를 써서 긍정 뷰가 비중 축소로 뒤집히던 문제).
코드 검사: 종목은 입력만, evidence_ids 는 창 안의 것만, 근거 없는 절대 뷰 제거, 같은 종목 양쪽 다리 금지, 신뢰도 상한.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any

from backend.analysis.common.llm import LlmClient, messages_from_prompts
from backend.analysis.common.prompts import load_prompts
from backend.analysis.m2_data import descriptor as D
from backend.analysis.m2_data.market_data import MarketDataView
from backend.analysis.m2_data.news import EvidenceWindow
from backend.analysis.settings import AnalysisSettings
from backend.pipeline.descriptor import Descriptor

STAGE = "09_views_news"


def trailing_12m_return(view: MarketDataView, tickers: list[str]) -> dict[str, float]:
    px = view.adj_close(tickers, view.as_of - dt.timedelta(days=380), fill=True)
    px = px.dropna(how="all")
    if px.empty:
        return {}
    first = px.bfill().iloc[0]
    return (px.iloc[-1] / first - 1).to_dict()


def _check(a: dict[str, Any]) -> None:
    if not (isinstance(a.get("sets"), list) and a["sets"]):
        raise ValueError("sets must be a non-empty list")


def generate_views(
    view: MarketDataView,
    tickers: list[str],
    mm: dict[str, Any],
    base_weights: dict[str, float],
    intent: dict[str, Any],
    desc: Descriptor,
    settings: AnalysisSettings,
    llm: LlmClient,
    evidence: EvidenceWindow,
    *,
    n_sets: int,
    views_per_set: int,
    stage_tag: str = STAGE,
) -> tuple[list[dict[str, Any]], list[str]]:
    """(sets, warnings). evidence.enough 가 아니면 호출자가 부르지 않는다 (기준 비중 fallback)."""
    ps = settings.portfolio
    max_conf = float(intent["news_tilt"]["max_view_confidence"])
    r12 = trailing_12m_return(view, tickers)
    rows = []
    for t in tickers:
        e = desc.by_ticker(t) or {}
        g = D.gics_model(e) if e else None
        rows.append(
            f"{t} | {e.get('name', t)} | {g.sector.name if g else ''} | {str(e.get('intro', ''))[:120]} | "
            f"{r12.get(t, float('nan')):+.1%} | {mm['ann_vol'][t]:.1%} | {mm['cap_weights'][t]:.1%} | {base_weights[t]:.1%}"
        )
    themes_block = "\n".join(f"- {th['id']}: {th['label_ko']} — {th['description_ko']}" for th in intent["interpretation"]["themes"])
    ev_lines, no_news, no_evidence = [], [], []
    for t in tickers:
        if not (evidence.by_ticker.get(t) or []):
            no_news.append(t)
        if not evidence.has_evidence(t):
            no_evidence.append(t)
    for r in evidence.records:
        if r["ticker"] in tickers:
            ev_lines.append(f"{r['evidence_id']} | {r['published_at']} | {r.get('source', '')}({r.get('language', '')}) | {r.get('publisher') or '-'} | {r['ticker']} | {r['title'][:140]}")
    dc_lines = [ln for ln in evidence.disclosure_lines() if ln.split(" | ")[4] in tickers] if evidence.disclosures else []
    ds = getattr(settings, "disclosures", None)
    dc_only_max = float(getattr(ds, "disclosure_only_max_confidence", 0.25) or 0.25)
    vars_ = dict(as_of=view.as_of, summary_ko=intent["interpretation"]["summary_ko"], themes_block=themes_block, stocks_block="\n".join(rows),
                 n_sets=n_sets, views_per_set=views_per_set, max_conf=max_conf, single_max_conf=ps.single_evidence_max_confidence,
                 news_window_days=(evidence.end - evidence.start).days, evidence_block="\n".join(ev_lines) or "(없음)",
                 dc_window_days=((evidence.end - evidence.dc_start).days if evidence.dc_start else 0), disclosure_block="\n".join(dc_lines) or "(없음)",
                 dc_only_max_conf=dc_only_max, no_news_tickers=", ".join(no_news) or "없음", no_evidence_tickers=", ".join(no_evidence) or "없음")  # fmt: skip
    system, user = load_prompts(STAGE, **vars_)  # 시스템 프롬프트는 상수 (날짜·조건은 사용자 메시지에만) → 제공자 프리픽스 캐시
    ans = llm.complete_json(stage_tag, messages_from_prompts(system, user), validator=_check, stub_key=STAGE)

    warnings: list[str] = []
    sets: list[dict[str, Any]] = []
    known = set(tickers)
    known_ev = evidence.ids
    owner: dict[str, set[str]] = {}  # 근거 id → 그 근거가 붙은 종목들
    for r in [*evidence.records, *(evidence.disclosures or [])]:
        owner.setdefault(str(r.get("evidence_id")), set()).add(r.get("ticker"))
    for s_ in ans.get("sets", []):
        seen: set = set()
        views = []
        opposite: list[str] = []  # 오름·내림이 함께 나와 둘 다 뺀 종목 (설명 문장에 덧붙인다)
        mirrored: list[str] = []  # 'A > B' 와 'B > A' 가 함께 나와 둘 다 뺀 상대 뷰 쌍
        sid = s_.get("scenario_id")
        for v in s_.get("views", []):
            legs = list(v.get("long", [])) + list(v.get("short", []))
            bad = [x for x in legs if x not in known]
            if bad:
                warnings.append(f"{sid}: view dropped, unknown tickers {bad}")
                continue
            if not v.get("long") or (v.get("type") == "relative" and not v.get("short")) or (v.get("type") == "absolute" and v.get("short")):
                warnings.append(f"{sid}: view dropped, malformed legs long={v.get('long')} short={v.get('short')}")
                continue
            key = (tuple(sorted(v["long"])), tuple(sorted(v.get("short", []))))
            mirror = (key[1], key[0])
            if v.get("type") == "relative" and mirror in seen:
                # 'A > B' 와 'B > A' 는 서로를 지워 사전 기대로 돌아가면서 적중 1·빗나감 1 을 늘 만든다 → 둘 다 뺀다 (057: 2종목 세트마다 양방향 상대 뷰)
                prev = next((x for x in views if (tuple(sorted(x["long"])), tuple(sorted(x.get("short", [])))) == mirror), None)
                if prev is not None:
                    views.remove(prev)
                    mirrored.append(f"{'·'.join(key[0])} > {'·'.join(key[1])}")
                    warnings.append(f"{sid}: mirrored relative views on {key} dropped (conflicting directions)")
                    seen.add(key)
                    continue
            if key in seen:
                # 같은 종목에 방향이 반대인 뷰가 또 있으면 둘 다 뺀다 — 먼저 나온 것만 남기면 순서가 결론을 정했다 (045: COIN 오름(0.25)·내림(0.30) 중 약한 오름이 남음)
                prev = next((x for x in views if (tuple(sorted(x["long"])), tuple(sorted(x.get("short", [])))) == key), None)
                if prev is not None and v.get("type") == "absolute" and str(v.get("direction") or "").lower() != str(prev.get("direction") or "").lower():
                    views.remove(prev)
                    opposite.append(key[0][0])
                    warnings.append(f"{sid}: opposite views on {key} dropped (conflicting directions)")
                else:
                    warnings.append(f"{sid}: duplicate view {key} dropped")
                continue
            seen.add(key)
            if set(v["long"]) & set(v.get("short", [])):
                warnings.append(f"{sid}: view dropped, same ticker on both legs {key}")
                continue
            if v["type"] == "absolute" and len(v["long"]) != 1:
                warnings.append(f"{sid}: absolute view dropped, needs exactly one ticker (got {v['long']})")
                continue
            c = float(v.get("confidence", 0))
            if not (ps.confidence_floor <= c <= max_conf):
                warnings.append(f"{sid}: confidence {c} clipped to [{ps.confidence_floor}, {max_conf}]")
                v["confidence"] = min(max(c, ps.confidence_floor), max_conf)
            _quantify(v, mm, tickers, ps, warnings, sid)
            v["horizon_months"] = _horizon_months(v.get("horizon_months"), warnings, sid)
            v["rationale_ko"] = plain_view_ko(v.get("rationale_ko") or "")
            ids, missing = [], []
            for raw_id in v.get("evidence_ids", []):
                eid = str(raw_id).strip()
                if eid not in known_ev and eid.isdecimal():
                    # 접두사 누락만 복원하며, 뉴스·공시 ID 가 겹치면 추측하지 않는다.
                    matches = [prefix + eid for prefix in ("ev", "dc") if prefix + eid in known_ev]
                    if len(matches) == 1:
                        eid = matches[0]
                if eid in known_ev:
                    ids.append(eid)
                else:
                    missing.append(raw_id)
            if missing:
                warnings.append(f"{sid}: unknown evidence ids {missing} removed")
            # 근거는 그 뷰의 종목에 붙은 뉴스·공시여야 한다 (043: AEP 에 붙은 'PNW(태평양 북서부) 겨울 정전' 기사만으로 Pinnacle West(PNW) 내림 뷰를 만들었다)
            legs = {*v["long"], *v.get("short", [])}
            foreign = [i for i in ids if owner.get(i) and not (owner[i] & legs)]
            if foreign:
                warnings.append(f"{sid}: evidence {foreign} belongs to other tickers, removed from view {key}")
                ids = [i for i in ids if i not in foreign]
            if not ids:
                warnings.append(f"{sid}: view {key} dropped (no valid evidence)")
                continue
            if v["type"] == "absolute" and not evidence.has_evidence(v["long"][0]):
                warnings.append(f"{sid}: absolute view on {v['long'][0]} without news/disclosure evidence dropped")
                continue
            v["evidence_ids"] = ids
            v["rationale_ko"] = _strip_unlisted_ids(v.get("rationale_ko") or "", set(ids))
            if len(ids) == 1 and float(v["confidence"]) > ps.single_evidence_max_confidence:
                warnings.append(f"{sid}: single-evidence view confidence {v['confidence']} clipped to {ps.single_evidence_max_confidence}")
                v["confidence"] = ps.single_evidence_max_confidence
            kinds = {"disclosure" if i.startswith("dc") else "news" for i in ids}
            v["evidence_type"] = "mixed" if len(kinds) > 1 else next(iter(kinds))  # 코드가 인용 ID 로 다시 계산 (LLM 값 무시)
            if kinds == {"disclosure"} and float(v["confidence"]) > dc_only_max:
                warnings.append(f"{sid}: disclosure-only view confidence {v['confidence']} clipped to {dc_only_max}")
                v["confidence"] = dc_only_max
            views.append(v)
        if len(views) > views_per_set:
            warnings.append(f"{sid}: {len(views)} views, truncated to {views_per_set}")
            views = views[:views_per_set]
        if views:
            # 설명은 LLM 이 뷰를 빼기 전에 쓴 것이라 뺀 뷰를 '반영했다' 고 말한다 (045 재실행: COIN 오름·내림을 둘 다 뺐는데 '상반된 신호로 반영했습니다')
            note = f" 같은 종목({', '.join(opposite)})에 오름·내림 뷰가 함께 나와 그 종목의 두 뷰는 반영하지 않았습니다." if opposite else ""
            if mirrored:
                note += f" 서로 반대인 상대 뷰({', '.join(mirrored)} 와 그 반대)가 함께 나와 둘 다 반영하지 않았습니다."
            rel = sum(1 for v in views if v.get("type") == "relative" and set(opposite) & {*v.get("long", []), *v.get("short", [])})
            if note and rel:  # 남은 상대 뷰는 반영된다 — 그 종목 비중이 왜 움직였는지 (055: 메리츠 오름·내림을 뺐는데 '…> 메리츠' 상대 뷰 둘이 비중을 줄였다)
                note += f" 그 종목이 걸린 상대 뷰 {rel}개는 반영했습니다."
            sig = tuple(sorted((tuple(x["long"]), tuple(x.get("short", [])), str(x.get("direction") or "")) for x in views))
            dup = next((x.get("scenario_id") for x in sets if x.get("_sig") == sig), None)
            if dup is not None:  # 앞 세트와 뷰가 똑같은 세트는 같은 대안이 둘로 보이게 할 뿐이다 (057: 2종목이라 다섯 세트가 모두 같았다)
                warnings.append(f"{sid}: same views as set {dup} -> dropped")
                continue
            sets.append({**s_, "views": views, "_sig": sig, **({"narrative_ko": (s_.get("narrative_ko") or "").rstrip() + note} if note else {})})
    for x in sets:
        x.pop("_sig", None)
    if len(sets) != n_sets:
        warnings.append(f"{len(sets)} sets returned, expected {n_sets}")
    return sets, warnings


_VIEW_EN = ((re.compile(r"(?<![A-Za-z])confidence(?![A-Za-z])\s*", re.I), "신뢰도"), (re.compile(r"(?<![A-Za-z])headlines?(?![A-Za-z])\s*", re.I), "헤드라인"))  # 둘 다 모음으로 끝나 뒤 조사(를·는·가)는 그대로 맞다


def _horizon_months(raw: Any, warnings: list[str], sid: Any) -> int:
    """뷰 기간은 형식상 1~60개월 (뷰 숫자는 연 수익률이라 계산에는 쓰지 않는다). 투자기간 15년을 그대로 적어 180개월이 되면
    형식 검사에서 10 단계 전체가 멈췄다 (045) → 잘라 넣고 경고만."""
    try:
        hm = int(raw if raw is not None else 12)
    except (TypeError, ValueError):
        hm = 12
    if not 1 <= hm <= 60:
        warnings.append(f"{sid}: view horizon_months {hm} clipped to [1, 60]")
        hm = min(max(hm, 1), 60)
    return hm


_ID_TOKEN = re.compile(r"(?<![A-Za-z0-9])(?:ev|dc)\d+(?!\d)")  # 한글도 \w 라 \b 로는 'ev123와' 를 못 가른다


def _strip_unlisted_ids(text: str, keep: set[str]) -> str:
    """뷰 설명 안의 근거 id 중 그 뷰의 근거(evidence_ids)가 아닌 것을 지운다 (052: '섀시 모듈 공급 보도(ev2691369와 별개로 … ev2691378)' —
    ev2691369 는 무관한 기사이고 리포트 근거 목록에도 없어 찾아볼 수 없었다)."""
    out = re.sub(r"(?<![A-Za-z0-9])((?:ev|dc)\d+)(?:와|과)\s*별개로\s*", lambda m: m.group(0) if m.group(1) in keep else "", text)
    out = re.sub(r"\[?(?<![A-Za-z0-9])((?:ev|dc)\d+)(?!\d)\]?(?:와|과|,)?\s*", lambda m: m.group(0) if m.group(1) in keep else "", out)
    out = re.sub(r"\(\s*\)", "", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def plain_view_ko(text: str) -> str:
    """뷰 설명의 영어 필드 이름·낱말을 한국어로 (039: '…평가(ev1566019)를 반영해 confidence를 제한합니다', '실적 headline만으로')."""
    for pat, ko in _VIEW_EN:
        text = pat.sub(ko, text)
    return text


def _quantify(v: dict[str, Any], mm: dict[str, Any], tickers: list[str], ps, warnings: list[str], sid: Any) -> None:
    """LLM 의 방향·강도를 사전 기대수익 대비 연 기대수익 Q(`expected_return_annual`)로 바꾼다.

    절대 뷰: Q = π_i + 방향 × k × σ_i. 상대 뷰: Q = (π_long − π_short) + k × σ(long − short) — 사전 기대 차이를 long 쪽으로 강도만큼 옮긴다.
    (처음에는 max(차이, 0) 을 썼는데, 사전 차이가 −10% 인 '약한' 뷰가 15%p 넘게 움직이는 강한 뷰가 됐다 — 000 CCI > SPG.)
    방향이 없으면(옛 캐시 응답·옛 stub) 숫자의 부호로 추정하고 경고를 남긴다. 상대 뷰의 down 은 다리를 바꿔 up 으로 둔다.
    """
    pi, vol = mm["implied_returns"], mm["ann_vol"]
    direction = str(v.get("direction") or "").lower()
    if v["type"] == "relative" and direction not in ("up", "down"):
        direction = "up"  # 상대 뷰는 방향을 안 써도 된다: long 이 short 를 이긴다는 뜻
    elif direction not in ("up", "down"):
        r = float(v.get("expected_return_annual", 0) or 0)
        direction = "down" if r < 0 else "up"
        warnings.append(f"{sid}: view {v['long']} has no direction; inferred '{direction}' from the sign of its number")
    if v["type"] == "relative" and direction == "down":
        v["long"], v["short"] = list(v["short"]), list(v["long"])
        direction = "up"
        warnings.append(f"{sid}: relative 'down' view rewritten as long {v['long']} over short {v['short']}")
    strength = str(v.get("strength") or "").lower()
    if strength not in ps.view_strength_k:
        warnings.append(f"{sid}: view {v['long']} strength {v.get('strength')!r} unknown; using 'medium'")
        strength = "medium"
    k = float(ps.view_strength_k[strength])
    if v["type"] == "absolute":
        t = v["long"][0]
        prior = float(pi[t])
        q = prior + (1 if direction == "up" else -1) * k * float(vol[t])
        lo, hi = ps.abs_return_range
    else:
        prior = sum(float(pi[t]) for t in v["long"]) / len(v["long"]) - sum(float(pi[t]) for t in v["short"]) / len(v["short"])
        q = prior + k * _spread_vol(v, mm, tickers)
        lo, hi = ps.abs_return_range  # 상대 뷰도 사전 차이가 음수일 수 있어 절대 뷰 범위로 자른다 (부호가 아니라 이동 방향이 뜻)
    if not (lo <= q <= hi):
        # 범위로 자르는 것은 이동 폭을 줄일 때만 쓴다. 사전 기대가 이미 범위 밖이면 범위 쪽으로 자르는 것이 이동을 키우거나(060: '약' 상대 뷰
        # VLO > BE 가 사전 −101% 에서 −50% 로 +51%p, SNDK 내림이 +148% 에서 +100% 로 −48%p) 방향을 뒤집는다(026·060 MRVL) → 그때는 강도만큼만 옮긴다
        qc = min(max(q, lo), hi)
        if (qc - prior) * (q - prior) > 0 and abs(qc - prior) <= abs(q - prior):
            warnings.append(f"{sid}: view {v['long']} return {q:.4f} clipped to [{lo}, {hi}]")
            q = qc
        else:
            warnings.append(f"{sid}: view {v['long']} prior {prior:.4f} outside [{lo}, {hi}]; kept the strength step ({q - prior:+.4f}) without clipping")
    v["direction"], v["strength"] = direction, strength
    v["prior_return"], v["expected_return_annual"] = round(prior, 6), round(q, 6)


def _spread_vol(v: dict[str, Any], mm: dict[str, Any], tickers: list[str]) -> float:
    """long 바스켓 − short 바스켓 수익률 차이의 연변동성 σ(P) = √(p'Σp). 공분산이 없으면 상관 0 으로 근사."""
    w = {t: 1 / len(v["long"]) for t in v["long"]}
    for t in v["short"]:
        w[t] = w.get(t, 0.0) - 1 / len(v["short"])
    cov, tk = mm.get("cov"), mm.get("tickers") or tickers
    if cov is not None and all(t in tk for t in w):
        idx = {t: i for i, t in enumerate(tk)}
        var = sum(w[a] * w[b] * float(cov[idx[a]][idx[b]]) for a in w for b in w)
    else:
        var = sum((w[t] * float(mm["ann_vol"][t])) ** 2 for t in w)
    return math.sqrt(max(var, 0.0))
