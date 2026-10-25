"""/reports: 목록, 상세(블록 문서 v2, 옛 문서는 읽을 때 정규화), 근거 색인 페이지·한 건, 체크포인트 상세, 전체 시계열, 결과 번들, 재분석 (M5-05 · M1-03 · 라운드 4)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from backend.analysis.api.routers import services
from backend.analysis.common.store import ComparisonStore
from backend.analysis.errors import NotFound
from backend.analysis.m5_backtest_report.report import present_doc
from backend.analysis.schemas.dialog import DialogState

router = APIRouter(tags=["reports"])


@router.get("/reports")
def list_reports(request: Request, limit: int = 100) -> list[dict[str, Any]]:
    sv = services(request)
    rows = {r["report_id"]: r for r in sv.repo.list_reports(limit)}
    out = []
    reqs = {d.request_id: d for d in sv.requests.list()}
    for e in sv.queue.list():
        if e.status not in ("success", "partial"):
            continue
        meta = rows.get(e.report_id or "")
        d = reqs.get(e.request_id)
        out.append({"report_id": e.report_id, "run_id": e.run_id, "request_id": e.request_id, "status": e.status, "has_report": bool(meta),
                    "strategy_name": (meta or {}).get("strategy_name"), "request_summary": (meta or {}).get("request_summary") or (d.idea if d else None),
                    "as_of": str((meta or {}).get("as_of") or ((d.derived or {}).get("as_of") if d else None) or ""), "created_at": e.finished_at,
                    "idea": d.idea if d else None, "mode": d.mode if d else None})  # fmt: skip
        if len(out) >= limit:
            break
    return out


@router.get("/reports/{report_id}")
def get_report(report_id: str, request: Request) -> dict[str, Any]:
    sv = services(request)
    row = sv.repo.get_report(report_id)
    if not row:
        try:
            e = sv.queue.get(report_id)
        except NotFound:
            raise NotFound(f"리포트 {report_id} 이 없습니다") from None
        if e.status in ("failed", "cancelled"):
            raise NotFound(f"실행이 {e.status} 상태라 리포트가 없습니다", code="REPORT_BLOCKED", details={"run_status": e.status, "error": e.error_message})
        raise NotFound("리포트가 아직 만들어지지 않았습니다", code="REPORT_NOT_READY", details={"run_status": e.status})
    doc = row["doc"] if isinstance(row, dict) and "doc" in row else row
    if doc.get("doc_version", 1) >= 2:
        return doc
    return present_doc(doc, sv.results(report_id))  # 라운드 3 이전 문서: 읽을 때 근거 슬림·요약 보강 (저장 문서는 그대로)


_KIND_ORDER = {"news": 0, "disclosure": 1, "financial": 2, "calc": 3, "data_quality": 4}


def _evidence_rows(R: dict[str, Any]) -> list[dict[str, Any]]:
    idx = R["evidence_index"]
    rows = [{"id": k, **v} for k, v in idx.items()]
    rows.sort(key=lambda e: (_KIND_ORDER.get(e["kind"], 9), -(len(e.get("published_at") or "")), str(e.get("published_at") or e.get("data_as_of") or ""), e["id"]))
    # 날짜 최신순 (뉴스·공시), 그 외는 id 순
    rows.sort(key=lambda e: (_KIND_ORDER.get(e["kind"], 9), "" if e["kind"] not in ("news", "disclosure") else "-" + str(e.get("available_on") or e.get("published_at") or ""), e["id"]))
    return rows


@router.get("/reports/{report_id}/evidence")
def list_evidence(report_id: str, request: Request, offset: int = 0, limit: int = 50, kind: str | None = None, ticker: str | None = None, q: str | None = None,
                  from_: str | None = Query(None, alias="from"), to: str | None = None, ids: str | None = None) -> dict[str, Any]:  # fmt: skip
    """근거 색인 페이지 조회 (출처 드로어). 필터: kind(news|disclosure|financial|calc), ticker, q(제목·id 부분 일치), from/to(날짜), ids(쉼표)."""
    sv = services(request)
    R = sv.results(report_id)
    if not R:
        raise NotFound(f"결과 {report_id} 이 없습니다")
    rows = _evidence_rows(R)
    limit = max(1, min(limit, 200))
    want = {x.strip() for x in ids.split(",") if x.strip()} if ids else None
    out = []
    for e in rows:
        if want is not None and e["id"] not in want:
            continue
        if kind and e["kind"] != kind:
            continue
        if ticker and ticker.upper() not in {t.upper() for t in e.get("tickers", [])}:
            continue
        d = str(e.get("available_on") or e.get("published_at") or e.get("data_as_of") or "")
        if from_ and d and d < from_:
            continue
        if to and d and d > to:
            continue
        if q:
            ql = q.lower()
            if ql not in (e.get("title") or "").lower() and ql not in e["id"].lower() and ql not in (e.get("event_label_ko") or "").lower():
                continue
        out.append(e)
    by_kind: dict[str, int] = {}
    for e in rows:
        by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
    return {"total": len(out), "offset": offset, "limit": limit, "items": out[offset : offset + limit], "by_kind": by_kind, "index_total": len(rows)}


@router.get("/reports/{report_id}/evidence/{eid}")
def get_evidence(report_id: str, eid: str, request: Request) -> dict[str, Any]:
    """근거 한 건 + 이 근거를 인용한 문장(섹션·블록 제목·문장)."""
    sv = services(request)
    R = sv.results(report_id)
    if not R or eid not in R["evidence_index"]:
        raise NotFound(f"근거 {eid} 이 없습니다")
    cited_in: list[dict[str, Any]] = []
    row = sv.repo.get_report(report_id)
    doc = (row["doc"] if isinstance(row, dict) and "doc" in row else row) if row else None
    tag = f"[{eid}]"
    if doc:
        for sec in doc["sections"]:
            for b in sec["blocks"]:
                title = b.get("title_ko") or ""
                if b["type"] == "paragraphs":
                    cited_in += [{"section_id": sec["id"], "block_title_ko": title, "text_ko": t} for t in b["items"] if tag in t]
                elif b["type"] == "cards":
                    cited_in += [{"section_id": sec["id"], "block_title_ko": it.get("title_ko") or title, "text_ko": it.get("text_ko", "")} for it in b["items"] if tag in it.get("text_ko", "")]
                elif b["type"] == "companies":
                    cited_in += [{"section_id": sec["id"], "block_title_ko": f"{it['ticker']} · {it.get('name', '')}", "text_ko": t} for it in b["items"] for t in it.get("rationale_ko", []) if tag in t]
                elif b["type"] == "timeline":
                    cited_in += [{"section_id": sec["id"], "block_title_ko": f"{it['date']} 뷰", "text_ko": v.get("summary_ko", "")} for it in b["items"] for v in it.get("views", []) if eid in v.get("evidence_ids", [])]
    return {"id": eid, **R["evidence_index"][eid], "cited_in": cited_in}


@router.get("/reports/{report_id}/checkpoints/{seq}")
def get_checkpoint(report_id: str, seq: int, request: Request, portfolio_id: str | None = None) -> dict[str, Any]:
    """리밸런싱 시점 하나의 상세: 보유·거래·구간 성과 + (walk-forward 면) 그날의 뷰·근거 창 요약."""
    sv = services(request)
    R = sv.results(report_id)
    if not R:
        raise NotFound(f"결과 {report_id} 이 없습니다")
    from backend.analysis.m5_backtest_report import report_blocks as B

    pid = portfolio_id or B.chosen_portfolio_id(R)[0]
    try:
        p = B.find(R, pid)
    except StopIteration:
        raise NotFound(f"포트폴리오 {pid} 이 없습니다") from None
    cp = next((c for c in (p.get("checkpoints") or []) if c["seq"] == seq), None)
    if cp is None:
        raise NotFound(f"체크포인트 {seq} 이 없습니다")
    wf = R["portfolio"].get("walkforward") or {}
    base_id = p.get("base_id") or pid
    bl = next((x for x in wf.get("portfolios", []) if x["id"] == base_id and x["kind"] == "black_litterman"), None)
    d = cp["date"]
    names = {t["ticker"]: t["name"] for t in R["selection"]["table"]}
    out = {"portfolio_id": pid, "label_ko": B.pf_label(p), "checkpoint": cp, "names": names, "views": [], "news_summary": None, "narrative_ko": None, "market_model": None}
    if bl is not None:
        out["views"] = bl["views_by_date"].get(d, [])
        out["news_summary"] = wf.get("news_summary", {}).get(d)
        out["narrative_ko"] = (bl.get("narrative_by_date") or {}).get(d)
        out["market_model"] = (wf.get("market_models_by_date") or {}).get(d)
        ids = {i for v in out["views"] for i in v.get("evidence_ids", [])}
        out["evidence"] = {i: R["evidence_index"][i] for i in sorted(ids) if i in R["evidence_index"]}
    return out


@router.get("/reports/{report_id}/series")
def get_series(report_id: str, request: Request, dataset: str = "index", ids: str | None = None) -> dict[str, Any]:
    """전체 해상도 시계열 (문서의 datasets 는 600점 넘으면 표본). dataset: index | value_usd | drawdown."""
    sv = services(request)
    R = sv.results(report_id)
    if not R:
        raise NotFound(f"결과 {report_id} 이 없습니다")
    if dataset not in ("index", "value_usd", "drawdown"):
        raise NotFound(f"dataset {dataset} 은 없습니다 (index | value_usd | drawdown)")
    from backend.analysis.m5_backtest_report import report_blocks as B

    want = {x.strip() for x in ids.split(",") if x.strip()} if ids else None
    series = {}
    for x in B.all_blocks(R):
        if want is None or x["id"] in want:
            series[x["id"]] = {"label_ko": B.pf_label(x), "kind": x["kind"], "values": x["series"][dataset]}
    if dataset == "value_usd" and (want is None or "net_invested" in want):
        chosen = B.chosen_portfolio_id(R)[0]
        p = B.find(R, chosen)
        led = {l["date"]: l["amount_usd"] for l in p["contribution_ledger"]}
        inv, cum = [], p["money"]["initial_usd"]
        for d in R["backtest"]["series_dates"]:
            cum += led.get(d, 0.0)
            inv.append(round(cum, 2))
        series["net_invested"] = {"label_ko": "투입 원금(누적)", "kind": "reference", "values": inv}
    return {"dataset": dataset, "dates": R["backtest"]["series_dates"], "series": series}


@router.get("/reports/{report_id}/results")
def get_results(report_id: str, request: Request) -> dict[str, Any]:
    art = services(request).repo.get_run_artifact(report_id)
    if not art:
        raise NotFound(f"결과 {report_id} 이 없습니다")
    return art["results"]


@router.post("/reports/{report_id}/rerun", response_model=DialogState)
def rerun(report_id: str, request: Request) -> DialogState:
    """같은 조건으로 최신 자료 재분석: 원 요청의 조건을 그대로 새 요청(mode=rerun)으로 시작한다."""
    sv = services(request)
    e = sv.queue.get(report_id)
    d = sv.requests.load(e.request_id)
    return sv.dialog().start(d.idea, overrides=d.overrides, mode="rerun", base_report_id=report_id, language=d.language, profile_version=d.profile_version)


class RevisionIn(BaseModel):
    text: str


@router.post("/reports/{report_id}/revisions", response_model=DialogState)
def create_revision(report_id: str, body: RevisionIn, request: Request) -> DialogState:
    """자연어 수정 요청 → 변경 초안(LLM 제안 + 코드 검증) → revision 모드 대화 시작. 확정하면 별도 실행이 돌고 끝나면 원안과 비교가 만들어진다."""
    return services(request).dialog().start_revision(report_id, body.text)


def _comparison(sv: Any, comparison_id: str) -> dict[str, Any]:
    cs = ComparisonStore(sv.store)
    try:
        return cs.load(comparison_id if comparison_id.startswith("cmp_") else f"cmp_{comparison_id}")
    except NotFound:
        try:
            e = sv.queue.get(comparison_id.removeprefix("cmp_"))
        except NotFound:
            raise NotFound(f"비교 {comparison_id} 이 없습니다") from None
        if e.status in ("queued", "running"):
            raise NotFound("수정안 분석이 아직 끝나지 않았습니다", code="COMPARISON_NOT_READY", details={"run_status": e.status}) from None
        raise NotFound("이 실행에는 비교 결과가 없습니다 (수정 요청으로 시작한 실행이 아니거나 실패)", code="COMPARISON_MISSING", details={"run_status": e.status}) from None


@router.get("/comparisons/{comparison_id}")
def get_comparison(comparison_id: str, request: Request) -> dict[str, Any]:
    return _comparison(services(request), comparison_id)


@router.get("/reports/{report_id}/comparison")
def get_report_comparison(report_id: str, request: Request) -> dict[str, Any]:
    """수정안 실행(report_id)의 원안 대비 비교. 수정안이 아니면 404 COMPARISON_MISSING."""
    return _comparison(services(request), report_id)
