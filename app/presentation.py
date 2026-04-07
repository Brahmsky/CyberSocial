from __future__ import annotations

import html
import re

from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app.config import Settings
from app.i18n import template_label, template_locale_url, template_relative_time, template_translate

INLINE_PATTERNS = (
    (re.compile(r"\*\*(.+?)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"`(.+?)`"), r"<code class=\"rounded bg-slate-950/80 px-1.5 py-0.5 text-cyan-200\">\1</code>"),
)


def _render_inline_markdown(value: str) -> str:
    rendered = html.escape(value)
    rendered = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        r'<a href="\2" class="text-cyan-300 underline decoration-cyan-400/40 underline-offset-4 hover:text-cyan-100">\1</a>',
        rendered,
    )
    for pattern, replacement in INLINE_PATTERNS:
        rendered = pattern.sub(replacement, rendered)
    return rendered


def _render_block(block: str) -> str:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if not lines:
        return ""
    if all(line.startswith(("- ", "* ")) for line in lines):
        items = "".join(f"<li>{_render_inline_markdown(line[2:])}</li>" for line in lines)
        return f"<ul>{items}</ul>"
    if lines[0].startswith("### "):
        return f"<h3>{_render_inline_markdown(lines[0][4:])}</h3>"
    if lines[0].startswith("## "):
        return f"<h2>{_render_inline_markdown(lines[0][3:])}</h2>"
    if lines[0].startswith("# "):
        return f"<h1>{_render_inline_markdown(lines[0][2:])}</h1>"
    return f"<p>{'<br>'.join(_render_inline_markdown(line) for line in lines)}</p>"


def render_markdown(value: str) -> Markup:
    value = value or ""
    blocks = [segment.strip() for segment in value.split("\n\n") if segment.strip()]
    return Markup("".join(_render_block(block) for block in blocks))


def build_templates(settings: Settings) -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(settings.templates_dir))
    templates.env.filters["markdown"] = render_markdown
    templates.env.filters["relative_time"] = template_relative_time
    templates.env.globals["t"] = template_translate
    templates.env.globals["label"] = template_label
    templates.env.globals["locale_url"] = template_locale_url
    return templates
