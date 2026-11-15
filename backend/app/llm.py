"""Plain-language explanations of results with Gemini.

The model never produces a number of its own: the code turns a result into a block of facts
(numbers already formatted), the model rewords it, and every number in the answer is checked
against the facts. If a number is not there, the answer is replaced by the code's own summary.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict, deque
from pathlib import Path
from typing import Optional

from .check import CheckError
from .models import ChatResponse, CheckResult, Co2ImpactResult, EventResult

DEFAULT_MODEL = "gemini-3.5-flash-lite"
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
KEY_FILE = Path.home() / ".config" / "gemini" / "api_key"
MAX_OUTPUT_TOKENS = 450
RATE_LIMIT = (20, 60.0)          # at most 20 model calls per 60 s across the server
CACHE_SIZE = 256

PROMPT_FILE = Path(__file__).with_name("prompts") / "chat_system.txt"
SYSTEM = PROMPT_FILE.read_text(encoding="utf-8").strip()   # drafted with Gemini 4 Hydrogen, see prompts/
SYSTEM_HASH = hashlib.sha256(SYSTEM.encode()).hexdigest()[:12]

_calls: deque[float] = deque()
_cache: "OrderedDict[str, ChatResponse]" = OrderedDict()
_lock = threading.Lock()


def _api_key() -> Optional[str]:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key and KEY_FILE.is_file():
        parts = KEY_FILE.read_text(encoding="utf-8").split()
        key = parts[-1] if parts else ""   # tolerate a "GEMINI_API_KEY = value" line
    return key or None


def _model() -> str:
    return os.environ.get("EV_LLM_MODEL", DEFAULT_MODEL)


# ---------- facts: code-formatted text the model may reword ----------

_CHECK_REASON = {
    "significant_trend": "the trend is statistically clear and goes the way the claim says",
    "opposite_trend": "the data show a clear trend in the opposite direction to the claim",
    "not_significant": "there is a trend on paper, but it is not larger than ordinary year-to-year swings",
    "short_series": "the record is too short to tell",
    "sources_disagree": "two data sources disagree on the direction",
    "not_robust": "the trend depends on which years are chosen",
    "no_variation": "the value never changes here in this season, so there is no trend to test",
}
_EVENT_REASON = {
    "clear_change": "a clear change at that time, not matched by fake event dates",
    "not_significant": "the difference before and after is not larger than ordinary month-to-month swings",
    "placebo_also_changes": "similar shifts also appear at fake event dates, so a broader trend or ordinary year-to-year swings can explain it",
    "no_placebo": "the record is too short to run the fake-dates check",
    "too_short": "too many months are missing before or after the event",
}
_VERDICT_WORD = {"confirmed": "Confirmed", "refuted": "Refuted", "not_proven": "Not proven",
                 "clear_change": "Clear change"}


def check_facts(r: CheckResult) -> tuple[str, str]:
    v, c = r.variable, r.case
    lines = [
        f'Claim: "{c.claim_text}"',
        f"Place: {r.case.place.name}. Variable: {v.label} ({v.units}). Years: {c.start_year}-{c.end_year}.",
        f"Verdict: {_VERDICT_WORD[r.verdict]} - {_CHECK_REASON[r.reason]}.",
        f"Trend: {r.sen.slope_per_decade:+.3g} {v.units} per decade (95% interval {r.sen.ci_low:+.3g} to {r.sen.ci_high:+.3g}); "
        f"chance-check p = {r.mk.p:.3g}.",
    ]
    if r.witness is not None:
        lines.append(f"Second source: station {r.witness.station.name}, agreement: {r.witness.agreement}.")
    if r.years_to_wait:
        lines.append(f"Years of data still needed to tell: {r.years_to_wait}.")
    lines += [f"Step - {s.title}: {s.value}. {s.detail}" for s in r.steps]
    if v.caveat:
        lines.append(f"Caveat: {v.caveat}")
    return "\n".join(lines), _fallback(f"{_VERDICT_WORD[r.verdict]}: {_CHECK_REASON[r.reason]}.", r.steps[-1].detail)


def event_facts(r: EventResult) -> tuple[str, str]:
    cmp_, s = r.compound, r.spec
    lines = [
        f"Place: {s.place.name}. Event: {s.event_label} ({s.event_month}). Compound: {cmp_.label}, {cmp_.units}.",
        f"What it is: {cmp_.definition}",
    ]
    if r.effect is not None and r.p is not None and r.ci_low is not None and r.ci_high is not None:
        rel = f" ({r.relative_change:+.0%})" if r.relative_change is not None else ""
        lines.append(f"After the event the level was {r.effect:+.3g} {cmp_.units}{rel} compared with before, "
                     f"relative to the surrounding area. Chance-check p = {r.p:.3g}; 95% interval "
                     f"{r.ci_low:+.3g} to {r.ci_high:+.3g}.")
        if r.placebo:
            lines.append(f"Fake-dates check: {r.placebo_larger} of {len(r.placebo)} fake event dates in other years "
                         "showed a shift as large as the real one.")
    word = _VERDICT_WORD.get(r.verdict, "Not proven")
    lines.append(f"Verdict: {word} - {_EVENT_REASON[r.reason]}.")
    lines += [f"Step - {st.title}: {st.value}. {st.detail}" for st in r.steps]
    if cmp_.caveat:
        lines.append(f"Caveat: {cmp_.caveat}")
    if cmp_.kind == "reanalysis":
        lines.append("This series is a model reanalysis, not a direct satellite measurement.")
    return "\n".join(lines), _fallback(f"{word}: {_EVENT_REASON[r.reason]}.", r.steps[-1].detail)


def co2_facts(r: Co2ImpactResult) -> tuple[str, str]:
    g, sp = r.global_co2, r.spec
    lines = [
        f"Source: {sp.mt_co2_per_year:g} Mt CO₂ per year for {sp.years:g} years"
        + (f' ("{sp.label}")' if sp.label else "") + ".",
        r.explanation,
        f"Global CO₂ today: {g.latest_ppm:.2f} ppm in {g.latest_month}; it grew {g.yoy_growth_ppm:+.2f} ppm over the last year"
        if g.yoy_growth_ppm is not None else f"Global CO₂ today: {g.latest_ppm:.2f} ppm in {g.latest_month}",
        f"Average growth since 1980: {g.sen_slope_ppm_per_year:+.3f} ppm per year (NOAA GML).",
        "One source adds a tiny part of a global total made of everyone's emissions.",
    ]
    if r.what_if_warming_c is not None and sp.what_if_ppm is not None and r.what_if_forcing_w_m2 is not None:
        w = r.what_if_warming_c
        lines.append(f"What-if: an atmosphere with {sp.what_if_ppm:g} ppm instead of {sp.c0_ppm:g} ppm gives "
                     f"{r.what_if_forcing_w_m2:.2f} W/m² of extra heating and {w.central:.2f} °C of transient warming "
                     f"(likely range {w.low:.2f} to {w.high:.2f} °C).")
    return "\n".join(lines), r.explanation


def _fallback(headline: str, detail: str) -> str:
    return f"{headline} {detail}".strip()


# ---------- guard + call ----------

# A number token: optional sign (only when not glued to a word, so "1998-2025" is two unsigned
# years), digits, optional decimals and optional exponent. Subscripts/superscripts (₂, ¹⁵) are not
# digits for this regex, so "NO₂" and "10¹⁵" stay safe while "NO2" and "10^15" are caught.
_NUM = re.compile(r"(?<![\w.])([+\-−]?)(\d+(?:\.\d+)?(?:e[+\-−]?\d+)?)", re.IGNORECASE)


def _numbers(text: str, comma: str = "thousands") -> list[tuple[str, str]]:
    """Signed number tokens. `comma` says how to read "1,543": as thousands (English) or as a
    decimal comma (Ukrainian). Two-digit or longer-than-three tails are always decimal."""
    text = re.sub(r"(?<=\d),(?=\d{1,2}(?!\d)|\d{4,})", ".", text)
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "." if comma == "decimal" else "", text)
    out = []
    for sign, num in _NUM.findall(text):
        num = num.lower().replace("−", "-")
        if "." in num and "e" not in num:
            num = num.rstrip("0").rstrip(".") or "0"
        out.append(("-" if sign in ("-", "−") else sign, num))
    return out


def _grounded(answer: list[tuple[str, str]], allowed: list[tuple[str, str]]) -> bool:
    unsigned = {n for _, n in allowed}
    signed = set(allowed)
    for sign, num in answer:
        if num not in unsigned:
            return False
        if sign and (sign, num) not in signed and not (sign == "+" and ("", num) in signed):
            return False
    return True


def numbers_are_grounded(answer: str, facts: str, question: str = "") -> bool:
    """Every number in the answer must occur in the facts (or be quoted from the question), with
    the same sign when the answer writes one: "+16.7" does not pass for a fact of "-16.7"."""
    allowed = _numbers(facts) + _numbers(question) + _numbers(question, "decimal")
    return any(_grounded(_numbers(answer, mode), allowed) for mode in ("thousands", "decimal"))


def _rate_ok() -> bool:
    now, (limit, window) = time.monotonic(), RATE_LIMIT
    with _lock:
        while _calls and now - _calls[0] > window:
            _calls.popleft()
        if len(_calls) >= limit:
            return False
        _calls.append(now)
        return True


class _Busy(Exception):
    """Gemini quota or rate limit (HTTP 429)."""


def _call_gemini(key: str, model: str, prompt: str) -> str:
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": MAX_OUTPUT_TOKENS},
    }).encode()
    req = urllib.request.Request(API_URL.format(model=model), data=body,
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise _Busy() from exc
        raise CheckError("llm_unavailable", f"The explanation service answered HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError) as exc:
        raise CheckError("llm_unavailable", "The explanation service did not respond.") from exc


def explain(kind: str, result: dict, question: Optional[str], lang: str) -> ChatResponse:
    builder, model_cls = {"check": (check_facts, CheckResult), "event": (event_facts, EventResult),
                          "co2": (co2_facts, Co2ImpactResult)}[kind]
    facts, fallback = builder(model_cls.model_validate(result))
    question = (question or "").strip() or None

    ck = hashlib.sha256(json.dumps([kind, facts, question, lang, _model(), SYSTEM_HASH]).encode()).hexdigest()
    with _lock:
        if ck in _cache:
            _cache.move_to_end(ck)
            return _cache[ck]

    key = _api_key()
    if key is None:
        raise CheckError("llm_unavailable", "Explanations are not configured on this server.")
    if not _rate_ok():
        raise CheckError("llm_unavailable", "Too many explanation requests; try again in a minute.")

    language = "Ukrainian" if lang == "uk" else "English"
    task = {"check": "TASK: explain this result, quoting its key numbers.",
            "event": "TASK: explain this result, quoting its key numbers.",
            "co2": "TASK: explain this result, quoting the emitted amount, the added ppm and the warming with their units."}[kind]
    prompt = f"Answer in {language}.\n\nFACTS:\n{facts}\n\n" + (f"QUESTION: {question}" if question else task)
    model = _model()
    text, grounded = "", False
    busy = False
    for _ in range(2):
        try:
            text = _call_gemini(key, model, prompt)
        except _Busy:
            busy = True
            break
        if text and numbers_are_grounded(text, facts, question or ""):
            grounded = True
            break
    if busy:   # quota hit: answer with the code's own summary, and do not cache it
        return ChatResponse(text=fallback, model="built-in (model busy)", grounded=False)
    resp = ChatResponse(text=text if grounded else fallback, model=model if grounded else "built-in",
                        grounded=grounded)
    with _lock:
        _cache[ck] = resp
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return resp
