"""Single swap point for LLM calls. Settings come from scripts/llm_config.py.

Mode (env MYFINSIGHT_LLM, default llm_config.DEFAULT_MODE):
  stub : return stubs/<stage>.example.json; the rendered prompt is still saved.
  api  : call the provider (OpenAI chat completions), parse the JSON answer, log usage + cost.

Every call writes output/prompts/<stage>[_b<batch>].md (exact system + user prompt).
In api mode it also writes output/llm_raw/<stage>[_b<batch>].json (raw answer, reusable as a stub)
and appends one JSON line to output/llm_usage.jsonl.
"""
import datetime as dt
import json, os, re, time
from pathlib import Path
import llm_config as C
from common import OUTPUT, STUBS, PROMPTS, load_json, render_template

_client = None


def load_prompts(stage_dir: str, **vars_):
    d = PROMPTS / stage_dir
    system = (d / "system_prompt.md").read_text(encoding="utf-8")
    user = render_template((d / "user_prompt.md").read_text(encoding="utf-8"), **vars_)
    return system, user


def _save_prompt(stage, system, user, batch=None):
    name = f"{stage}" + (f"_b{batch}" if batch is not None else "") + ".md"
    p = OUTPUT / "prompts" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# SYSTEM\n\n{system}\n\n# USER\n\n{user}\n", encoding="utf-8")
    return p


def _api_key():
    key = os.environ.get(C.API_KEY_ENV)
    if not key and Path(C.ENV_FILE).exists():
        kv = dict(re.findall(r'^\s*([A-Z0-9_]+)\s*=\s*"?([^"\n]*)"?\s*$', Path(C.ENV_FILE).read_text(), flags=re.M))
        key = kv.get(C.API_KEY_ENV)
    if not key:
        raise RuntimeError(f"{C.API_KEY_ENV} not found in env or {C.ENV_FILE}")
    return key


def _client_openai():
    global _client
    if _client is None:
        import openai
        _client = openai.OpenAI(api_key=_api_key(), timeout=C.TIMEOUT_S)
    return _client


def _setting(stage, name):
    return C.STAGE_OVERRIDES.get(stage, {}).get(name, getattr(C, name))


def _parse_json(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    return json.loads(t)


def _cost_usd(model, prompt, cached, completion, cache_write=0):
    p = C.PRICING_USD_PER_1M.get(model)
    if not p:
        return None
    return round(((prompt - cached) * p["input"] + cached * p["cached_input"]
                  + cache_write * p.get("cache_write", 0) + completion * p["output"]) / 1e6, 6)


def _call_openai(stage, system, user, batch):
    import openai
    client = _client_openai()
    kw = {"model": C.MODEL, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
          "max_completion_tokens": _setting(stage, "MAX_OUTPUT_TOKENS")}
    if _setting(stage, "TEMPERATURE") is not None: kw["temperature"] = _setting(stage, "TEMPERATURE")
    if _setting(stage, "REASONING_EFFORT") is not None: kw["reasoning_effort"] = _setting(stage, "REASONING_EFFORT")
    if _setting(stage, "RESPONSE_FORMAT_JSON"): kw["response_format"] = {"type": "json_object"}

    t0, last = time.time(), None
    for attempt in range(C.RETRIES + 1):
        try:
            resp = client.chat.completions.create(**kw); break
        except (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError) as e:
            last = e
            if attempt == C.RETRIES: raise
            print(f"  [llm] {type(e).__name__} on {stage}; retry in {C.RETRY_BACKOFF_S}s", flush=True)
            time.sleep(C.RETRY_BACKOFF_S)
    elapsed = round(time.time() - t0, 1)
    text = resp.choices[0].message.content or ""
    u = resp.usage
    cached = (getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0)
    reasoning = (getattr(getattr(u, "completion_tokens_details", None), "reasoning_tokens", 0) or 0)
    cache_write = (getattr(getattr(u, "prompt_tokens_details", None), "cache_write_tokens", 0) or 0)
    rec = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "run_id": os.environ.get("MYFINSIGHT_RUN_ID", "adhoc"),
           "stage": stage, "batch": batch, "model": resp.model, "prompt_tokens": u.prompt_tokens, "cached_tokens": cached,
           "completion_tokens": u.completion_tokens, "reasoning_tokens": reasoning, "cache_write_tokens": cache_write,
           "cost_usd": _cost_usd(C.MODEL, u.prompt_tokens, cached, u.completion_tokens, cache_write), "elapsed_s": elapsed,
           "finish_reason": resp.choices[0].finish_reason}
    C.USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(C.USAGE_LOG, "a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    raw = C.RAW_DIR / (f"{stage}" + (f"_b{batch}" if batch is not None else "") + ".json")
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(text, encoding="utf-8")
    print(f"  [llm] {stage}{'' if batch is None else f' b{batch}'}: {u.prompt_tokens} in / {u.completion_tokens} out "
          f"(cached {cached}, reasoning {reasoning}) ${rec['cost_usd']} {elapsed}s finish={rec['finish_reason']}", flush=True)
    if rec["finish_reason"] == "length":
        raise RuntimeError(f"[llm] {stage}: answer truncated (max_completion_tokens too small)")
    try:
        return _parse_json(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"[llm] {stage}: answer is not valid JSON ({e}); raw saved at {raw}")


def call_llm(stage: str, system: str, user: str, *, batch=None, stub_file=None) -> dict:
    """Return the LLM's JSON answer for `stage` (stub or real, per MYFINSIGHT_LLM / llm_config)."""
    prompt_path = _save_prompt(stage, system, user, batch)
    mode = os.environ.get("MYFINSIGHT_LLM", C.DEFAULT_MODE)
    if mode == "stub":
        stub = Path(stub_file) if stub_file else STUBS / f"{stage}.example.json"
        if not stub.exists():
            raise FileNotFoundError(f"[llm:stub] no stub for stage '{stage}': {stub}  (prompt saved to {prompt_path})")
        return load_json(stub)
    if mode == "api":
        if C.PROVIDER != "openai":
            raise NotImplementedError(f"provider {C.PROVIDER}")
        return _call_openai(stage, system, user, batch)
    raise ValueError(f"MYFINSIGHT_LLM={mode!r} (expected 'stub' or 'api')")
