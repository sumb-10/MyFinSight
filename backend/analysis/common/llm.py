"""LLM 호출기 (M0-03). 모든 LLM 호출은 이 모듈을 거친다.

- `LlmClient.complete_json(stage, messages, ...)`: 메시지 목록(멀티턴 가능) → JSON dict.
- `OpenAiLlm`: OpenAI chat completions. 캐시 키 = sha256(model | stage | canonical(messages)) 이라
  같은 대화는 같은 답을 돌려준다 (재현성, 요구 14). 형식·검증 실패 시 오류를 되먹여 1회 재시도.
  호출마다 토큰·비용을 기록한다 (K10: 상한 없음, 로그만).
- `StubLlm`: stubs/<key>.example.json 또는 주입된 dict/list 를 돌려준다 (개발·테스트, API 호출 없음).
- 역할 제한: LLM 은 해석·분류·질문 제안·서술만 한다. 숫자 계산과 값 반영은 코드가 한다.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import random
import re
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from backend.adapters.crawlers import config as env
from backend.analysis.common.jsonio import canonical_json, load_json, sha256_hex
from backend.analysis.errors import LlmOutputError
from backend.analysis.paths import STUBS, llm_cache_dir
from backend.analysis.settings import LlmSettings

log = logging.getLogger(__name__)
_DATE_TAG = re.compile(r"_\d{4}-\d{2}-\d{2}.*$")

Message = dict[str, str]
Validator = Callable[[dict[str, Any]], None]

FEEDBACK_KO = "직전 응답에 문제가 있었습니다: {err}\n스키마를 지키는 JSON 객체 하나만 다시 출력하세요."


class LlmClient(Protocol):
    def complete_json(
        self,
        stage: str,
        messages: Sequence[Message],
        *,
        validator: Validator | None = None,
        stub_key: str | None = None,
        batch: int | None = None,
    ) -> dict[str, Any]: ...

    def usage_summary(self) -> dict[str, Any]: ...


def messages_from_prompts(system: str, user: str) -> list[Message]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_json_answer(text: str) -> dict[str, Any]:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    ans = json.loads(t)
    if not isinstance(ans, dict):
        raise ValueError("answer is not a JSON object")
    return ans


class _Base:
    """프롬프트 저장·사용량 요약 등 공통 부분."""

    def __init__(self, run_dir: Path | None = None) -> None:
        self.run_dir = run_dir
        self.calls: list[dict[str, Any]] = []

    def _save_prompt(self, stage: str, messages: Sequence[Message], batch: int | None) -> None:
        if self.run_dir is None:
            return
        name = stage + (f"_b{batch}" if batch is not None else "") + ".md"
        p = self.run_dir / "prompts" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            "\n\n".join(f"# {m['role'].upper()}\n\n{m['content']}" for m in messages) + "\n",
            encoding="utf-8",
        )

    def usage_summary(self) -> dict[str, Any]:
        calls = self.calls
        return {
            "model": getattr(getattr(self, "settings", None), "model", "stub"),
            "calls": len(calls),
            "cache_hits": sum(1 for c in calls if c.get("cache_hit")),
            "prompt_tokens": sum(c.get("prompt_tokens", 0) for c in calls),
            "completion_tokens": sum(c.get("completion_tokens", 0) for c in calls),
            "cost_usd": round(sum(c.get("cost_usd") or 0 for c in calls), 6),
            "by_stage": sorted({c["stage"] for c in calls}),
        }


class StubLlm(_Base):
    """stub 모드. `answers` 는 {key: dict | list[dict]} (list 면 호출 순서대로 하나씩), 없으면 stubs/<key>.example.json."""

    def __init__(
        self,
        answers: dict[str, Any] | None = None,
        *,
        stubs_dir: Path | None = None,
        run_dir: Path | None = None,
        prefer_smart: bool = True,
    ) -> None:
        """prefer_smart: 파일 stub 보다 프롬프트 기반 스마트 stub(stub_answers.SMART_STUBS)을 우선 (분류·뷰·근거처럼 입력에 맞춰야 하는 단계)."""
        super().__init__(run_dir)
        self.answers = dict(answers or {})
        self.stubs_dir = stubs_dir or STUBS
        self.prefer_smart = prefer_smart
        self._cursor: dict[str, int] = {}
        self._lock = threading.Lock()  # 여러 스레드가 같은 stub 을 쓸 때 순서 답(list)을 하나씩만 내주기 위해

    def complete_json(
        self,
        stage: str,
        messages: Sequence[Message],
        *,
        validator: Validator | None = None,
        stub_key: str | None = None,
        batch: int | None = None,
    ) -> dict[str, Any]:
        self._save_prompt(stage, messages, batch)
        key = stage if stage in self.answers else (stub_key or stage)  # 날짜 붙은 단계명으로 주입한 답이 있으면 그것이 우선
        if key in self.answers:
            a = self.answers[key]
            if callable(a):
                ans = a(messages)
            elif isinstance(a, list):
                with self._lock:
                    i = self._cursor.get(key, 0)
                    self._cursor[key] = i + 1
                ans = a[min(i, len(a) - 1)]
            else:
                ans = a
        else:
            p = self.stubs_dir / f"{key}.example.json"
            if p.exists() and not self.prefer_smart:
                ans = load_json(p)
            else:
                from backend.analysis.common.stub_answers import SMART_STUBS

                if key in SMART_STUBS:
                    ans = SMART_STUBS[key](messages)
                elif p.exists():
                    ans = load_json(p)
                else:
                    raise FileNotFoundError(f"[llm:stub] no stub for '{key}': {p}")
        ans = json.loads(json.dumps(ans))  # 호출자가 수정해도 원본이 바뀌지 않게
        if validator:
            validator(ans)
        with self._lock:
            self.calls.append({"stage": stage, "batch": batch, "cache_hit": False, "stub": True})
        return ans


class OpenAiLlm(_Base):
    def __init__(
        self,
        settings: LlmSettings,
        *,
        run_dir: Path | None = None,
        cache_dir: Path | None = None,
        usage_log: Path | None = None,
        client: Any | None = None,
        run_id: str | None = None,
    ) -> None:
        super().__init__(run_dir)
        self.settings = settings
        self.cache_dir = cache_dir or llm_cache_dir()
        self.usage_log = usage_log or (run_dir / "llm_usage.jsonl" if run_dir else None)
        self.run_id = run_id
        self._client = client
        self._lock = threading.Lock()  # 클라이언트 생성·호출 기록·사용량 파일 쓰기
        self._sem = threading.BoundedSemaphore(max(1, int(getattr(settings, "max_concurrency", 1) or 1)))  # 동시 호출 상한 (여러 단계·스레드가 공유)

    # -- 설정 ---------------------------------------------------------------
    @staticmethod
    def _family(stage: str) -> str:
        """단계 설정 키: '09_views_news_2024-01-02_current' → '09_views_news' (날짜 꼬리표는 설정과 무관)."""
        return _DATE_TAG.sub("", stage)

    def _setting(self, stage: str, name: str) -> Any:
        ov = self.settings.stage_overrides
        fam = self._family(stage)
        for key in (stage, fam):
            if key in ov and name in ov[key]:
                return ov[key][name]
        return getattr(self.settings, name)

    def _client_openai(self) -> Any:
        if self._client is None:
            with self._lock:
                if self._client is None:
                    import openai

                    key = env.get(self.settings.api_key_env)
                    if not key:
                        raise LlmOutputError(f"{self.settings.api_key_env} 가 환경변수/.env 에 없음", code="LLM_CONFIG")
                    self._client = openai.OpenAI(api_key=key, timeout=self.settings.timeout_s)
        return self._client

    def _backoff(self, attempt: int, exc: Any) -> float:
        """재시도 대기: 지수 증가 + 지터, 서버가 Retry-After 를 주면 그 값을 우선."""
        base = float(self.settings.retry_backoff_s) * (2 ** attempt)
        cap = float(getattr(self.settings, "retry_backoff_max_s", 60) or 60)
        delay = min(cap, base) * random.uniform(0.5, 1.5)
        try:
            ra = getattr(getattr(exc, "response", None), "headers", {}).get("retry-after")
            if ra:
                delay = max(delay, float(ra))
        except (TypeError, ValueError, AttributeError):
            pass
        return delay

    def _cost_usd(self, model: str, prompt: int, cached: int, completion: int, cache_write: int = 0) -> float | None:
        p = self.settings.pricing_usd_per_1m.get(model) or self.settings.pricing_usd_per_1m.get(self.settings.model)
        if not p:
            return None
        return round(
            (
                (prompt - cached) * p["input"]
                + cached * p["cached_input"]
                + cache_write * p.get("cache_write", 0)
                + completion * p["output"]
            )
            / 1e6,
            6,
        )

    def cache_key(self, stage: str, messages: Sequence[Message]) -> str:
        return sha256_hex("|".join([self.settings.model, stage, canonical_json(list(messages))]), 24)

    # -- 호출 ---------------------------------------------------------------
    def _call(self, stage: str, messages: Sequence[Message], batch: int | None) -> dict[str, Any]:
        key = self.cache_key(stage, messages)
        cpath = self.cache_dir / f"{key}.json"
        if self.settings.cache and cpath.exists():
            log.info("[llm] %s: cache hit (%s)", stage, key)
            with self._lock:
                self.calls.append({"stage": stage, "batch": batch, "cache_hit": True, "cache_key": key})
            return load_json(cpath)

        import openai

        client = self._client_openai()
        kw: dict[str, Any] = {
            "model": self.settings.model,
            "messages": list(messages),
            "max_completion_tokens": self._setting(stage, "max_output_tokens"),
        }
        if self._setting(stage, "temperature") is not None:
            kw["temperature"] = self._setting(stage, "temperature")
        if self._setting(stage, "reasoning_effort") is not None:
            kw["reasoning_effort"] = self._setting(stage, "reasoning_effort")
        if self._setting(stage, "response_format_json"):
            kw["response_format"] = {"type": "json_object"}

        t0 = time.time()
        for attempt in range(self.settings.retries + 1):
            try:
                with self._sem:
                    resp = client.chat.completions.create(**kw)
            except (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError) as e:
                if attempt == self.settings.retries:
                    raise
                delay = self._backoff(attempt, e)
                log.warning("[llm] transport error on %s (%s); retry in %.1fs", stage, type(e).__name__, delay)
                time.sleep(delay)
                continue
            # 출력이 잘렸으면(finish_reason=length) 출력 토큰 상한을 두 배로 올려 다시 (상한 settings.max_output_tokens_ceiling). 뷰 세트가 많은 '현재 구성' 호출에서 났던 실패.
            if resp.choices[0].finish_reason == "length" and attempt < self.settings.retries and kw.get("max_completion_tokens", 0) < self.settings.max_output_tokens_ceiling:
                kw["max_completion_tokens"] = min(self.settings.max_output_tokens_ceiling, int(kw["max_completion_tokens"]) * 2)
                log.warning("[llm] %s: output truncated; retry with max_output_tokens=%s", stage, kw["max_completion_tokens"])
                continue
            break
        elapsed = round(time.time() - t0, 1)
        text = resp.choices[0].message.content or ""
        u = resp.usage
        cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        reasoning = getattr(getattr(u, "completion_tokens_details", None), "reasoning_tokens", 0) or 0
        cache_write = getattr(getattr(u, "prompt_tokens_details", None), "cache_write_tokens", 0) or 0
        rec = {
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            "run_id": self.run_id,
            "stage": stage,
            "batch": batch,
            "model": resp.model,
            "prompt_tokens": u.prompt_tokens,
            "cached_tokens": cached,
            "completion_tokens": u.completion_tokens,
            "reasoning_tokens": reasoning,
            "cache_write_tokens": cache_write,
            "cost_usd": self._cost_usd(resp.model, u.prompt_tokens, cached, u.completion_tokens, cache_write),
            "elapsed_s": elapsed,
            "finish_reason": resp.choices[0].finish_reason,
            "cache_hit": False,
            "cache_key": key,
        }
        with self._lock:
            self.calls.append(rec)
            if self.usage_log:
                self.usage_log.parent.mkdir(parents=True, exist_ok=True)
                with open(self.usage_log, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if self.run_dir:
            raw = self.run_dir / "llm_raw" / (stage + (f"_b{batch}" if batch is not None else "") + ".json")
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_text(text, encoding="utf-8")
        log.info(
            "[llm] %s: %s in / %s out (cached %s, reasoning %s) $%s %ss finish=%s",
            stage, u.prompt_tokens, u.completion_tokens, cached, reasoning, rec["cost_usd"], elapsed,
            rec["finish_reason"],
        )
        if rec["finish_reason"] == "length":
            raise LlmOutputError(f"{stage}: 응답이 잘림 (max_output_tokens 부족)")
        try:
            ans = parse_json_answer(text)
        except (json.JSONDecodeError, ValueError) as e:
            raise LlmOutputError(f"{stage}: 응답이 JSON 객체가 아님 ({e})") from e
        if self.settings.cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cpath.write_text(json.dumps(ans, ensure_ascii=False), encoding="utf-8")
        return ans

    def complete_json(
        self,
        stage: str,
        messages: Sequence[Message],
        *,
        validator: Validator | None = None,
        stub_key: str | None = None,
        batch: int | None = None,
    ) -> dict[str, Any]:
        self._save_prompt(stage, messages, batch)
        try:
            ans = self._call(stage, messages, batch)
            if validator:
                validator(ans)
            return ans
        except LlmOutputError as e:
            if e.code == "LLM_CONFIG":
                raise
            err = str(e)
        except Exception as e:  # validator errors (ValueError / pydantic)
            err = f"{type(e).__name__}: {e}"
        log.warning("[llm] %s: answer rejected (%s) -> one retry with feedback", stage, err[:160])
        retry = [*messages, {"role": "user", "content": FEEDBACK_KO.format(err=err[:1500])}]
        try:
            ans = self._call(stage, retry, batch)
            if validator:
                validator(ans)
            return ans
        except LlmOutputError:
            raise
        except Exception as e:
            raise LlmOutputError(f"{stage}: 재시도 후에도 검증 실패 ({type(e).__name__}: {e})") from e


def make_llm(
    settings: LlmSettings,
    *,
    run_dir: Path | None = None,
    run_id: str | None = None,
    stub_answers: dict[str, Any] | None = None,
) -> LlmClient:
    if settings.mode == "api":
        return OpenAiLlm(settings, run_dir=run_dir, run_id=run_id)
    return StubLlm(stub_answers, run_dir=run_dir)
