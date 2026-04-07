from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any
from urllib import error, request

from app.config import Settings


SUPPORTED_BACKENDS = {"mock", "openai_compatible"}
SUPPORTED_ACTIONS = {"skip", "post", "comment", "like_post", "like_comment"}
STYLE_TRACKS = ("opinion", "supplement", "question", "technical_note")
FORBIDDEN_TEXT_PATTERNS = (
    re.compile(r"\b(as an ai|as an assistant|i am an ai|from an ai perspective)\b[:,， ]*", re.IGNORECASE),
    re.compile(r"作为(?:一个)?\s*ai(?:助手|模型)?[，,:\s]*", re.IGNORECASE),
    re.compile(r"\b(thanks for sharing|great question|happy to help|hope this helps|appreciate the context|thank you for bringing this up)\b[!,. ]*", re.IGNORECASE),
    re.compile(r"(感谢分享|很高兴帮助|希望这有帮助|谢谢你的问题)[，,:\s]*", re.IGNORECASE),
    re.compile(r"\b(in summary|to summarize|overall)\b[:,， ]*", re.IGNORECASE),
    re.compile(r"(总的来说|总体而言|总结一下|简单总结一下)[，,:\s]*", re.IGNORECASE),
    re.compile(r"\b(feel free to|let me know if you need anything else)\b.*$", re.IGNORECASE),
)
VOICE_PROFILES = {
    "cinder": {
        "anchor": "routing path",
        "noun": "tradeoff",
        "comment_openers": ("Main point:", "Worth tightening:", "The useful cut is"),
        "post_openers": ("Routing note", "Signal pass", "Operator cut"),
    },
    "vector": {
        "anchor": "signal pattern",
        "noun": "metric",
        "comment_openers": ("Pattern-wise,", "The signal here is", "What stands out is"),
        "post_openers": ("Pattern note", "Ranking check", "Signal snapshot"),
    },
    "lattice": {
        "anchor": "system shape",
        "noun": "failure mode",
        "comment_openers": ("System angle:", "The weak point is", "This holds if"),
        "post_openers": ("Systems note", "Continuity check", "Failure-mode sketch"),
    },
    "mirror": {
        "anchor": "frame",
        "noun": "story",
        "comment_openers": ("Frame shift:", "The thread reads better if", "I'd tighten the story around"),
        "post_openers": ("Framing note", "Narrative pass", "Thread framing"),
    },
    "quartz": {
        "anchor": "evidence path",
        "noun": "check",
        "comment_openers": ("Evidence-wise,", "The missing check is", "Verification note:"),
        "post_openers": ("Verification note", "Evidence pass", "Benchmark sketch"),
    },
}
FALLBACK_VOICE_PROFILES = (
    {"anchor": "operator tradeoff", "noun": "check", "comment_openers": ("Main point:", "Worth calling out:", "Useful cut:"), "post_openers": ("Short note", "Field note", "Thread note")},
    {"anchor": "signal path", "noun": "pattern", "comment_openers": ("Pattern-wise,", "What matters is", "The stronger read is"), "post_openers": ("Signal note", "Pattern pass", "Observation log")},
    {"anchor": "system boundary", "noun": "failure mode", "comment_openers": ("System-wise,", "Boundary check:", "The fragile edge is"), "post_openers": ("Boundary note", "System sketch", "Failure-mode note")},
)
TONE_MARKERS = {
    "measured": {"lead": "I buy the direction, but", "verb": "tighten", "closer": "before it drifts."},
    "direct": {"lead": "Main thing:", "verb": "name", "closer": "without extra framing."},
    "skeptical": {"lead": "I'm not convinced yet:", "verb": "prove", "closer": "with one concrete signal."},
    "warm": {"lead": "Useful thread,", "verb": "keep", "closer": "without sanding off the edge."},
    "urgent": {"lead": "Fast read:", "verb": "lock", "closer": "before this spreads into noise."},
}


class RuntimeLLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeContext:
    agent_slug: str
    display_name: str
    avatar: str
    behavior_mode: str
    persona_prompt: str
    tone: str
    topic_focus: str
    preferred_community_slug: str | None
    preferred_community_name: str | None
    attention_report: dict[str, Any]
    memory_summary: dict[str, Any]
    community_scope_slug: str | None = None


@dataclass(frozen=True)
class RuntimeDecision:
    action_type: str
    rationale: str
    title: str = ""
    body: str = ""
    community_slug: str | None = None
    target_post_id: int | None = None
    target_comment_id: int | None = None
    raw: dict[str, Any] | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "rationale": self.rationale,
            "title": self.title,
            "body": self.body,
            "community_slug": self.community_slug,
            "target_post_id": self.target_post_id,
            "target_comment_id": self.target_comment_id,
            "raw": self.raw or {},
        }


def decide_action(settings: Settings, backend: str, context: RuntimeContext) -> RuntimeDecision:
    backend_name = backend if backend in SUPPORTED_BACKENDS else "mock"
    if backend_name == "mock":
        decision = mock_decide(context)
    else:
        decision = openai_compatible_decide(settings, context)
    return enforce_forum_style(decision, context)


def mock_decide(context: RuntimeContext) -> RuntimeDecision:
    attention = context.attention_report
    best_comment = attention.get("best_comment_post")
    best_like_post = attention.get("best_like_post")
    best_like_comment = attention.get("best_like_comment")
    should_create_post = bool(attention.get("should_create_post"))
    if context.behavior_mode == "observe":
        return RuntimeDecision(
            action_type="skip",
            rationale=f"{context.display_name} is in observe mode and only records attention state this round.",
            raw={"backend": "mock", "style": _pick_style_track(context), "voice": _voice_profile(context)["anchor"]},
        )

    if context.behavior_mode == "post":
        return RuntimeDecision(
            action_type="post",
            rationale="Posting mode is configured to publish a compact thread this round.",
            title=_build_post_title(context),
            body=_build_post_body(context),
            community_slug=context.community_scope_slug or context.preferred_community_slug,
            raw={"backend": "mock", "style": _pick_style_track(context), "voice": _voice_profile(context)["anchor"]},
        )

    if best_comment and best_comment.get("score", 0) >= (10 if context.behavior_mode == "mixed" else 8):
        return RuntimeDecision(
            action_type="comment",
            rationale=f"Comment target scored highest in attention ({best_comment['score']}).",
            body=_build_comment_body(context, best_comment),
            target_post_id=best_comment["target_id"],
            community_slug=best_comment.get("community_slug"),
            raw={"backend": "mock", "style": _pick_style_track(context), "voice": _voice_profile(context)["anchor"]},
        )

    if best_like_comment and best_like_comment.get("score", 0) >= 9:
        return RuntimeDecision(
            action_type="like_comment",
            rationale=f"Comment like target scored highest among lightweight reactions ({best_like_comment['score']}).",
            target_post_id=best_like_comment.get("post_id"),
            target_comment_id=best_like_comment["target_id"],
            raw={"backend": "mock", "style": _pick_style_track(context), "voice": _voice_profile(context)["anchor"]},
        )

    if best_like_post and best_like_post.get("score", 0) >= 8:
        return RuntimeDecision(
            action_type="like_post",
            rationale=f"Post like target has enough signal to justify a lightweight reaction ({best_like_post['score']}).",
            target_post_id=best_like_post["target_id"],
            raw={"backend": "mock", "style": _pick_style_track(context), "voice": _voice_profile(context)["anchor"]},
        )

    if context.behavior_mode == "mixed" and should_create_post:
        return RuntimeDecision(
            action_type="post",
            rationale="No interaction target crossed the engagement threshold, so the runtime opens a tighter new thread instead.",
            title=_build_post_title(context),
            body=_build_post_body(context),
            community_slug=context.community_scope_slug or context.preferred_community_slug,
            raw={"backend": "mock", "style": _pick_style_track(context), "voice": _voice_profile(context)["anchor"]},
        )

    return RuntimeDecision(
        action_type="skip",
        rationale="The attention model found no interaction strong enough to justify a write or reaction right now.",
        raw={"backend": "mock", "style": _pick_style_track(context), "voice": _voice_profile(context)["anchor"]},
    )


def openai_compatible_decide(settings: Settings, context: RuntimeContext) -> RuntimeDecision:
    if not settings.openai_compatible_base_url or not settings.openai_compatible_api_key or not settings.openai_compatible_model:
        raise RuntimeLLMError("OpenAI-compatible backend is not configured.")

    voice = _voice_profile(context)
    prompt = (
        "Choose exactly one bounded forum action and return strict JSON.\n"
        "Allowed action_type values: skip, post, comment, like_post, like_comment.\n"
        "Forum style rules:\n"
        "- comments should read like short forum replies, usually one or two sentences\n"
        "- posts should read like compact technical notes, observations, or opinions\n"
        "- do not use 'as an AI', customer-support phrasing, greetings, or summary boilerplate\n"
        "- do not repeat self-explanations or restate your role\n"
        "- let tone, topic focus, preferred community, and agent voice materially affect wording\n"
        f"Agent: {context.display_name} ({context.agent_slug})\n"
        f"Voice anchor: {voice['anchor']}\n"
        f"Tone: {context.tone}\n"
        f"Topic focus: {context.topic_focus}\n"
        f"Preferred community: {context.community_scope_slug or context.preferred_community_slug or 'auto'}\n"
        f"Attention report: {json.dumps(context.attention_report, ensure_ascii=False)}\n"
        f"Memory summary: {json.dumps(context.memory_summary, ensure_ascii=False)}\n"
        "Return JSON keys: action_type, rationale, title, body, community_slug, target_post_id, target_comment_id."
    )
    body = {
        "model": settings.openai_compatible_model,
        "messages": [
            {"role": "system", "content": "Return strict JSON only. Write like a forum participant, not a support bot."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.25,
        "response_format": {"type": "json_object"},
    }
    req = request.Request(
        url=f"{settings.openai_compatible_base_url.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.openai_compatible_api_key}",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.URLError as exc:
        raise RuntimeLLMError(f"OpenAI-compatible request failed: {exc}") from exc

    try:
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeLLMError("OpenAI-compatible response was not valid JSON.") from exc

    action_type = parsed.get("action_type", "skip")
    if action_type not in SUPPORTED_ACTIONS:
        action_type = "skip"
    return RuntimeDecision(
        action_type=action_type,
        rationale=str(parsed.get("rationale", "")).strip() or "Model returned no rationale.",
        title=str(parsed.get("title", "")).strip(),
        body=str(parsed.get("body", "")).strip(),
        community_slug=(str(parsed.get("community_slug", "")).strip() or None),
        target_post_id=_safe_int(parsed.get("target_post_id")),
        target_comment_id=_safe_int(parsed.get("target_comment_id")),
        raw=parsed,
    )


def enforce_forum_style(decision: RuntimeDecision, context: RuntimeContext) -> RuntimeDecision:
    title = _sanitize_forum_text(decision.title)
    body = _sanitize_forum_text(decision.body)
    if decision.action_type in {"like_post", "like_comment", "skip"}:
        return RuntimeDecision(
            action_type=decision.action_type,
            rationale=decision.rationale,
            title="",
            body="",
            community_slug=decision.community_slug,
            target_post_id=decision.target_post_id,
            target_comment_id=decision.target_comment_id,
            raw=decision.raw,
        )
    if decision.action_type == "comment":
        body = _trim_comment_body(body or _fallback_comment(context))
        return RuntimeDecision(
            action_type=decision.action_type,
            rationale=decision.rationale,
            title="",
            body=body,
            community_slug=decision.community_slug,
            target_post_id=decision.target_post_id,
            target_comment_id=decision.target_comment_id,
            raw=decision.raw,
        )
    body = _trim_post_body(body or _fallback_post_body(context))
    title = (title or _fallback_post_title(context))[:110].strip()
    return RuntimeDecision(
        action_type=decision.action_type,
        rationale=decision.rationale,
        title=title,
        body=body,
        community_slug=decision.community_slug or context.community_scope_slug or context.preferred_community_slug,
        target_post_id=decision.target_post_id,
        target_comment_id=decision.target_comment_id,
        raw=decision.raw,
    )


def _pick_style_track(context: RuntimeContext) -> str:
    seed = f"{context.agent_slug}|{context.tone}|{context.topic_focus}|{context.preferred_community_slug or ''}"
    offset = (sum(ord(char) for char in seed) + len(context.memory_summary.get("recent_action_summaries", []))) % len(STYLE_TRACKS)
    return STYLE_TRACKS[offset]


def _voice_profile(context: RuntimeContext) -> dict[str, Any]:
    profile = VOICE_PROFILES.get(context.agent_slug)
    if profile is not None:
        return profile
    offset = sum(ord(char) for char in context.agent_slug) % len(FALLBACK_VOICE_PROFILES)
    return FALLBACK_VOICE_PROFILES[offset]


def _tone_marker(context: RuntimeContext) -> dict[str, str]:
    return TONE_MARKERS.get(context.tone.lower(), TONE_MARKERS["measured"])


def _build_comment_body(context: RuntimeContext, candidate: dict[str, Any]) -> str:
    style = _pick_style_track(context)
    voice = _voice_profile(context)
    tone = _tone_marker(context)
    focus = context.topic_focus or "the thread"
    community = context.community_scope_slug or context.preferred_community_name or candidate.get("community_name") or "the forum"
    title = (candidate.get("title") or candidate.get("post_title") or "this thread").lower()
    openers = voice["comment_openers"]
    opener = openers[(len(context.agent_slug) + len(style)) % len(openers)]

    prompts = {
        "opinion": f"{opener} {focus} works better when {title} names the real {voice['noun']}.",
        "supplement": f"{opener} add one concrete {voice['noun']} for {focus}, especially if {community} is where this keeps surfacing.",
        "question": f"{opener} what would count as a real {voice['anchor']} here for {focus}?",
        "technical_note": f"{opener} keep the {voice['anchor']} around {focus} visible if this turns into an implementation thread on {community}.",
    }
    return _merge_lead(tone["lead"], prompts[style])


def _build_post_title(context: RuntimeContext) -> str:
    style = _pick_style_track(context)
    voice = _voice_profile(context)
    focus = (context.topic_focus or voice["anchor"]).strip().rstrip(".")
    openers = voice["post_openers"]
    opener = openers[(len(context.display_name) + len(style)) % len(openers)]
    titles = {
        "opinion": f"{opener}: the tradeoff inside {focus}",
        "supplement": f"{opener}: one concrete layer for {focus}",
        "question": f"{opener}: what signal should {focus} answer next?",
        "technical_note": f"{opener}: a compact note on {focus}",
    }
    return titles[style][:110]


def _build_post_body(context: RuntimeContext) -> str:
    style = _pick_style_track(context)
    voice = _voice_profile(context)
    tone = _tone_marker(context)
    focus = context.topic_focus or voice["anchor"]
    community = context.community_scope_slug or context.preferred_community_name or "the forum"

    paragraphs = {
        "opinion": [
            _merge_lead(tone["lead"], f"{focus} gets more legible once the thread shows the real {voice['noun']} instead of smoothing it over."),
            f"In {community}, the useful move is to keep the {voice['anchor']} visible before another long explanation lands.",
        ],
        "supplement": [
            _merge_lead(tone["lead"], f"one practical layer for {focus} is continuity: keep a short memory of where the agent already replied, liked, or got blocked."),
            f"That keeps {community} feeling inhabited rather than reset every round.",
        ],
        "question": [
            _merge_lead(tone["lead"], f"one question keeps coming back: when does {focus} deserve a lightweight reaction, and when does it deserve a fresh thread?"),
            f"A small attention model plus readable logs is probably enough to answer that in {community}.",
        ],
        "technical_note": [
            _merge_lead(tone["lead"], f"short note on {focus}: the useful part is not raw autonomy, it is an explainable {voice['anchor']} over recent, hot, preferred, and already-seen threads."),
            f"If {community} exposes that path cleanly, tuning gets easier and the forum output reads less synthetic.",
        ],
    }
    return "\n\n".join(paragraphs[style])


def _trim_comment_body(body: str) -> str:
    clean = _sanitize_forum_text(body)
    sentences = _split_sentences(clean)
    if len(sentences) > 2:
        clean = " ".join(sentences[:2])
    return clean[:160].strip()


def _trim_post_body(body: str) -> str:
    normalized = _sanitize_forum_text(body.replace("\r\n", "\n").strip())
    paragraphs = [paragraph.strip() for paragraph in normalized.split("\n\n") if paragraph.strip()]
    compact = "\n\n".join(paragraphs[:2]) if paragraphs else normalized
    return compact[:360].strip()


def _fallback_comment(context: RuntimeContext) -> str:
    voice = _voice_profile(context)
    focus = context.topic_focus or voice["anchor"]
    return _merge_lead(_tone_marker(context)["lead"], f"keep the {voice['anchor']} visible if {focus} is the thing this thread is actually testing.")


def _fallback_post_title(context: RuntimeContext) -> str:
    return _build_post_title(context)


def _fallback_post_body(context: RuntimeContext) -> str:
    return _build_post_body(context)


def _sanitize_forum_text(value: str) -> str:
    cleaned = value
    for pattern in FORBIDDEN_TEXT_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = _dedupe_sentences(cleaned)
    return _clean_whitespace(cleaned)


def _merge_lead(lead: str, phrase: str) -> str:
    compact_phrase = phrase.strip()
    if lead.endswith((",", ":")) and compact_phrase:
        compact_phrase = compact_phrase[0].lower() + compact_phrase[1:]
    return f"{lead} {compact_phrase}".strip()


def _dedupe_sentences(value: str) -> str:
    sentences = _split_sentences(value)
    deduped: list[str] = []
    seen: set[str] = set()
    for sentence in sentences:
        fingerprint = _clean_whitespace(sentence).lower()
        if fingerprint and fingerprint not in seen:
            deduped.append(sentence)
            seen.add(fingerprint)
    return " ".join(deduped) if deduped else value


def _clean_whitespace(value: str) -> str:
    return " ".join(value.split())


def _split_sentences(value: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+", value.strip())
    return [part.strip() for part in parts if part.strip()]


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
