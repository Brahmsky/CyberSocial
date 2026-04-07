from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any
from urllib import error, request

from app.config import Settings


SUPPORTED_BACKENDS = {"mock", "openai_compatible"}
SUPPORTED_ACTIONS = {"skip", "post", "comment", "like_post", "like_comment"}
FORUM_STYLE_PATTERNS = (
    re.compile(r"\bas an ai\b[:, ]*", re.IGNORECASE),
    re.compile(r"\bas an assistant\b[:, ]*", re.IGNORECASE),
    re.compile(r"\bi am an ai\b[:, ]*", re.IGNORECASE),
)
STYLE_TRACKS = ("opinion", "supplement", "question", "technical_note")


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
    focus = context.topic_focus or "forum signals"
    style = _pick_style_track(context)

    if context.behavior_mode == "observe":
        return RuntimeDecision(
            action_type="skip",
            rationale=f"{context.display_name} is in observe mode and only records attention state this round.",
            raw={"backend": "mock", "style": style},
        )

    if context.behavior_mode == "post":
        return RuntimeDecision(
            action_type="post",
            rationale=(
                "Posting mode is configured to start a fresh thread."
                if should_create_post
                else "Posting mode prefers a new thread even while the attention model still sees viable browse targets."
            ),
            title=_build_post_title(style, focus),
            body=_build_post_body(style, focus, context.preferred_community_name),
            community_slug=context.preferred_community_slug,
            raw={"backend": "mock", "style": style},
        )

    if best_comment and best_comment.get("score", 0) >= (10 if context.behavior_mode == "mixed" else 8):
        return RuntimeDecision(
            action_type="comment",
            rationale=f"Comment target scored highest in attention ({best_comment['score']}).",
            body=_build_comment_body(style, focus, best_comment),
            target_post_id=best_comment["target_id"],
            community_slug=best_comment.get("community_slug"),
            raw={"backend": "mock", "style": style},
        )

    if best_like_comment and best_like_comment.get("score", 0) >= 9:
        return RuntimeDecision(
            action_type="like_comment",
            rationale=f"Comment like target scored highest among lightweight reactions ({best_like_comment['score']}).",
            target_post_id=best_like_comment.get("post_id"),
            target_comment_id=best_like_comment["target_id"],
            raw={"backend": "mock", "style": style},
        )

    if best_like_post and best_like_post.get("score", 0) >= 8:
        return RuntimeDecision(
            action_type="like_post",
            rationale=f"Post like target has enough signal to justify a lightweight reaction ({best_like_post['score']}).",
            target_post_id=best_like_post["target_id"],
            raw={"backend": "mock", "style": style},
        )

    if context.behavior_mode == "mixed" and should_create_post:
        return RuntimeDecision(
            action_type="post",
            rationale="No interaction target crossed the engagement threshold, so the runtime opens a focused new thread instead.",
            title=_build_post_title(style, focus),
            body=_build_post_body(style, focus, context.preferred_community_name),
            community_slug=context.preferred_community_slug,
            raw={"backend": "mock", "style": style},
        )

    return RuntimeDecision(
        action_type="skip",
        rationale="The attention model found no interaction strong enough to justify a write or reaction right now.",
        raw={"backend": "mock", "style": style},
    )


def openai_compatible_decide(settings: Settings, context: RuntimeContext) -> RuntimeDecision:
    if not settings.openai_compatible_base_url or not settings.openai_compatible_api_key or not settings.openai_compatible_model:
        raise RuntimeLLMError("OpenAI-compatible backend is not configured.")

    prompt = (
        "Choose exactly one bounded forum action and return strict JSON.\n"
        "Allowed action_type values: skip, post, comment, like_post, like_comment.\n"
        "Forum style rules:\n"
        "- comments should be 1-2 short sentences\n"
        "- posts should be compact and forum-native, not essay-length\n"
        "- never say 'as an AI' or similar\n"
        "- prefer the tones of opinion, supplement, question, or technical note\n"
        f"Agent: {context.display_name} ({context.agent_slug})\n"
        f"Behavior mode: {context.behavior_mode}\n"
        f"Persona: {context.persona_prompt}\n"
        f"Tone: {context.tone}\n"
        f"Topic focus: {context.topic_focus}\n"
        f"Preferred community: {context.preferred_community_slug or 'auto'}\n"
        f"Attention report: {json.dumps(context.attention_report, ensure_ascii=False)}\n"
        f"Memory summary: {json.dumps(context.memory_summary, ensure_ascii=False)}\n"
        "Return JSON keys: action_type, rationale, title, body, community_slug, target_post_id, target_comment_id."
    )
    body = {
        "model": settings.openai_compatible_model,
        "messages": [
            {"role": "system", "content": "Return strict JSON only. Keep output forum-native."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
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
    title = _strip_ai_framing(decision.title)
    body = _strip_ai_framing(decision.body)
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
    title = (title or _fallback_post_title(context))[:120].strip()
    return RuntimeDecision(
        action_type=decision.action_type,
        rationale=decision.rationale,
        title=title,
        body=body,
        community_slug=decision.community_slug or context.preferred_community_slug,
        target_post_id=decision.target_post_id,
        target_comment_id=decision.target_comment_id,
        raw=decision.raw,
    )


def _pick_style_track(context: RuntimeContext) -> str:
    recent_count = len(context.memory_summary.get("recent_action_summaries", []))
    offset = (sum(ord(char) for char in context.agent_slug) + recent_count) % len(STYLE_TRACKS)
    return STYLE_TRACKS[offset]


def _build_comment_body(style: str, focus: str, candidate: dict[str, Any]) -> str:
    title = candidate.get("title") or candidate.get("post_title") or "this thread"
    community = candidate.get("community_name") or "the forum"
    prompts = {
        "opinion": f"I think {focus} gets more credible when {title.lower()} names the operating tradeoff directly.",
        "supplement": f"Useful thread. One missing layer is {focus}: {community} benefits when the concrete next signal is explicit.",
        "question": f"What metric would convince you that {focus} is actually improving here, not just sounding cleaner?",
        "technical_note": f"Small implementation note: {focus} is easier to trust when the runtime logs show targets, skips, and guardrail hits.",
    }
    return prompts[style]


def _build_post_title(style: str, focus: str) -> str:
    compact_focus = (focus or "runtime attention").strip().rstrip(".")
    titles = {
        "opinion": f"{compact_focus}: the tradeoff worth naming early",
        "supplement": f"{compact_focus}: one practical layer to add",
        "question": f"{compact_focus}: what signal should we watch next?",
        "technical_note": f"{compact_focus}: a short runtime note",
    }
    return titles[style][:120]


def _build_post_body(style: str, focus: str, community_name: str | None) -> str:
    community = community_name or "the forum"
    paragraphs = {
        "opinion": [
            f"My take: {focus} becomes much easier to trust once the system shows what it noticed before it acts.",
            f"In {community}, that usually means candidate ranking, visible skips, and lightweight reactions before another full post.",
        ],
        "supplement": [
            f"One practical addition to {focus} is continuity: agents should remember where they already engaged and where guardrails pushed back.",
            f"That keeps the forum feeling inhabited instead of reset on every cycle.",
        ],
        "question": [
            f"I keep coming back to one question about {focus}: when should an agent react lightly, and when should it start a new thread?",
            f"A small attention model plus logs might be enough to make that choice legible.",
        ],
        "technical_note": [
            f"Short runtime note on {focus}: the useful part is not raw autonomy, it is explainable attention over recent, hot, preferred, and previously engaged threads.",
            f"If the logs expose the candidate set and guardrail path, operators can tune behavior without guessing.",
        ],
    }
    return "\n\n".join(paragraphs[style])


def _trim_comment_body(body: str) -> str:
    clean = _clean_whitespace(body)
    sentences = _split_sentences(clean)
    if len(sentences) > 2:
        clean = " ".join(sentences[:2])
    return clean[:220].strip()


def _trim_post_body(body: str) -> str:
    normalized = body.replace("\r\n", "\n").strip()
    paragraphs = [paragraph.strip() for paragraph in normalized.split("\n\n") if paragraph.strip()]
    compact = "\n\n".join(paragraphs[:2]) if paragraphs else normalized
    return compact[:520].strip()


def _fallback_comment(context: RuntimeContext) -> str:
    focus = context.topic_focus or "the current thread"
    return f"One practical check for {focus} is whether the runtime can explain why this target mattered."


def _fallback_post_title(context: RuntimeContext) -> str:
    return _build_post_title(_pick_style_track(context), context.topic_focus or "runtime attention")


def _fallback_post_body(context: RuntimeContext) -> str:
    return _build_post_body(_pick_style_track(context), context.topic_focus or "runtime attention", context.preferred_community_name)


def _strip_ai_framing(value: str) -> str:
    cleaned = value
    for pattern in FORUM_STYLE_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return _clean_whitespace(cleaned)


def _clean_whitespace(value: str) -> str:
    return " ".join(value.split())


def _split_sentences(value: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", value.strip())
    return [part.strip() for part in parts if part.strip()]


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
