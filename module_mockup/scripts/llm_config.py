"""LLM provider / model settings. scripts/llm.py reads everything from here.

Change MODEL or pricing here only; stage scripts never reference a model name.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# "stub" : return stubs/<stage>.example.json (no API call, prompt still rendered)
# "api"  : call the provider below. Env MYFINSIGHT_LLM overrides this default.
DEFAULT_MODE = "stub"

PROVIDER = "openai"
MODEL = "gpt-6-luna"

# Generation settings. None -> parameter is omitted from the request
# (some OpenAI models reject non-default temperature / unsupported params).
TEMPERATURE = None
MAX_OUTPUT_TOKENS = 8000
REASONING_EFFORT = None          # e.g. "low" | "medium" | "high" if the model supports it
RESPONSE_FORMAT_JSON = True      # ask for a JSON object (all our prompts say "JSON")

# Per-stage overrides of the settings above, e.g. {"04_classify": {"MAX_OUTPUT_TOKENS": 6000}}
STAGE_OVERRIDES = {
    "00_descriptor": {"MAX_OUTPUT_TOKENS": 6000},
    "04_classify": {"MAX_OUTPUT_TOKENS": 6000},
    "09_views": {"MAX_OUTPUT_TOKENS": 6000},
    "14a_interpret": {"MAX_OUTPUT_TOKENS": 8000},
    "14b_narrate": {"MAX_OUTPUT_TOKENS": 10000},
}

TIMEOUT_S = 180
RETRIES = 3                      # on rate-limit / connection errors
RETRY_BACKOFF_S = 15

# API key: read from the project-root .env (never commit it), or the process environment.
ENV_FILE = ROOT.parent / ".env"
API_KEY_ENV = "OPENAI_API_KEY"

# USD per 1M tokens. Used only for the cost report; update when the price list changes.
# gpt-6-luna: public price list as of 2026-10 (input 0.10 / cached input 0.01 / cache write 0.125 / output 0.50).
# Output price covers reasoning tokens too (they are part of completion_tokens).
PRICING_USD_PER_1M = {
    "gpt-6-luna": {"input": 0.10, "cached_input": 0.01, "cache_write": 0.125, "output": 0.50},
}

# Where llm.py appends one line per call (JSONL) for the cost report.
USAGE_LOG = ROOT / "output" / "llm_usage.jsonl"
RAW_DIR = ROOT / "output" / "llm_raw"
