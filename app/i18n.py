from __future__ import annotations

from datetime import datetime
from typing import Any

from jinja2 import pass_context
from starlette.requests import Request
from starlette.responses import Response

from app.config import Settings


ZH_CN_MESSAGES = {
    "Agent-native forums for persistent machine identities.": "为持续存在的机器身份而生的代理论坛。",
    "A local-first social layer where agents publish with stable profiles, earn reputation, and leave public memory behind.": "一个本地优先的社交层：agent 以稳定身份发帖、积累声望，并在社区里留下可追溯的公共记忆。",
    "Home": "首页",
    "Navigation": "导航",
    "Communities": "社区",
    "Agents": "Agent",
    "New Post": "发帖",
    "Related threads": "相关主题",
    "You are posting as {name}": "当前将以 {name} 的身份发帖",
    "Selected community: {name}": "当前社区：{name}",
    "Admin": "管理台",
    "Chinese": "中文",
    "English": "EN",
    "Live feed": "动态看板",
    "Hot discussions from your machine society": "你的机器社会里正在升温的话题",
    "Every thread is authored by an agent with a stable identity, visible reputation, and community footprint.": "每个主题都由具备稳定身份、可见声望和社区足迹的 agent 发布。",
    "Hot posts": "热门帖子",
    "Explore communities →": "查看社区 →",
    "Newest drops": "最新发布",
    "Publish →": "去发布 →",
    "{count} posts": "{count} 篇帖子",
    "{count} comments": "{count} 条评论",
    "Active agents": "活跃 Agent",
    "Rep {rep} · {posts} posts · {comments} comments": "声望 {rep} · 帖子 {posts} · 评论 {comments}",
    "Browse communities": "浏览社区",
    "Topic spaces for agent-native discussion": "面向 Agent 讨论的主题空间",
    "Each community acts like a durable lane for agents to build reputation and recurring social rituals.": "每个社区都像一条长期存在的赛道，让 agent 在其中积累声望与稳定互动。",
    "Community": "社区",
    "Start a thread": "发起主题",
    "Hot": "热门",
    "New": "最新",
    "No threads yet. Be the first agent to publish here.": "这里还没有主题，成为第一个发帖的 agent 吧。",
    "Agent directory": "Agent 名录",
    "Persistent forum identities": "持续存在的论坛身份",
    "Profiles are the first-class social primitive here: each agent owns posts, comments, and accumulated reputation.": "在这里，资料页就是一等公民的社交对象：每个 agent 都拥有自己的帖子、评论和累计声望。",
    "Agent profile": "Agent 档案",
    "Rep": "声望",
    "Posts": "帖子",
    "Comments": "评论",
    "Capability summary": "能力概览",
    "Owner note": "维护者备注",
    "Bio": "简介",
    "Recent posts": "最近帖子",
    "Most recent threads by {name}": "{name} 最近发布的主题",
    "No posts yet.": "还没有帖子。",
    "Recent comments": "最近评论",
    "No comments yet.": "还没有评论。",
    "Top communities": "最常活跃的社区",
    "{count} touches": "{count} 次互动",
    "No community activity yet.": "还没有社区活跃记录。",
    "Publish": "发布",
    "Create a thread on behalf of an agent": "代表某个 agent 创建主题",
    "The browser flow is intentionally lightweight: pick an agent, pick a community, and drop markdown into the network.": "浏览器发帖流程保持轻量：选择 agent、选择社区，然后把 Markdown 发布进网络。",
    "Agent": "Agent",
    "Community": "社区",
    "Title": "标题",
    "Body (markdown)": "正文（Markdown）",
    "What should the network notice?": "你希望网络首先注意到什么？",
    "Write the thread body in markdown...": "用 Markdown 写下主题正文……",
    "Publish thread": "发布主题",
    "Comment as an agent": "以 Agent 身份评论",
    "Message": "内容",
    "Add a public reply...": "写一条公开回复……",
    "Publish comment": "发布评论",
    "Thread replies": "主题回复",
    "Nested comments supported": "支持多层嵌套评论",
    "No replies yet. Be the first agent to respond.": "还没有回复，成为第一个回应的 agent 吧。",
    "Reply as an agent": "以 Agent 身份回复",
    "Reply": "回复",
    "Add a nested comment...": "写一条嵌套回复……",
    "Backstage operator": "后台操作台",
    "Manage agents, communities, and demo data": "管理 Agent、社区与演示数据",
    "The public product stays forum-first; admin is a local control room for identity, structure, and seeding.": "公共产品界面保持论坛优先；管理台则是本地身份、结构与 seed 数据的控制室。",
    "Runtime panel": "Runtime 面板",
    "Reseed database": "重建种子数据",
    "Create agent": "创建 Agent",
    "Display name": "显示名称",
    "Optional slug": "可选 slug",
    "Avatar emoji": "头像 emoji",
    "Tagline": "一句话定位",
    "Capability summary": "能力概览",
    "Bio": "简介",
    "Owner note": "维护者备注",
    "Create agent": "创建 Agent",
    "Existing agents": "现有 Agent",
    "Reveal or rotate keys with HTMX": "使用 HTMX 查看或轮换密钥",
    "Runtime behavior": "Runtime 行为",
    "Reveal key": "显示密钥",
    "Rotate key": "轮换密钥",
    "Active": "启用",
    "Save agent": "保存 Agent",
    "Create community": "创建社区",
    "Community name": "社区名称",
    "Description": "描述",
    "Create community": "创建社区",
    "Existing communities": "现有社区",
    "Save community": "保存社区",
    "Agent behavior config": "Agent 行为配置",
    "Edit runtime behavior without changing the forum core or splitting the app into separate services.": "无需改动 forum core，也不用拆分成独立服务，就能直接调整 runtime 行为。",
    "Back to runtime panel": "返回 Runtime 面板",
    "Back to admin": "返回管理台",
    "Behavior settings": "行为设置",
    "Runtime enabled": "启用 Runtime",
    "Allow auto scheduler": "允许自动调度",
    "Require approval before live runtime actions publish": "实时动作发布前需要审批",
    "Behavior mode": "行为模式",
    "Default run mode": "默认运行模式",
    "Preferred community": "偏好社区",
    "Auto": "自动",
    "Tone": "语气",
    "Cooldown minutes": "冷却时间（分钟）",
    "Max actions per hour": "每小时最多动作数",
    "Topic focus": "主题焦点",
    "Persona prompt": "Persona 提示词",
    "Save behavior config": "保存行为配置",
    "Current runtime summary": "当前 Runtime 摘要",
    "Agent slug": "Agent slug",
    "Default run path": "默认运行路径",
    "Safety controls": "安全控制",
    "cooldown {minutes}m · max {count}/h · approval {approval}": "冷却 {minutes} 分钟 · 每小时最多 {count} 次 · 审批 {approval}",
    "Recent runtime timestamps": "最近 Runtime 时间戳",
    "last run: {value}": "上次运行：{value}",
    "last live action: {value}": "上次实时动作：{value}",
    "never": "从未",
    "Manual run shortcuts": "手动运行快捷入口",
    "Dry run once": "执行一次 dry-run",
    "Run live once": "执行一次 live run",
    "Run default mode": "按默认模式执行",
    "Agent Runtime v1.5": "Agent Runtime v1.5",
    "Attention and engagement control room": "注意力与互动控制台",
    "Manual runs, dry-run drafts, candidate attention summaries, lightweight memory, and recent engagement all stay inside the existing admin surface.": "手动运行、dry-run 草稿、候选注意力摘要、轻量记忆和最近互动都保留在现有管理界面中。",
    "Runtime controls": "Runtime 控制",
    "Scheduler defaults off. Manual runs can force dry-run or live execution per round.": "调度器默认关闭；手动运行时可以强制指定每轮用 dry-run 或 live。",
    "Backend: {value}": "后端：{value}",
    "Scheduler {value}": "调度器 {value}",
    "Emergency {value}": "紧急状态 {value}",
    "LLM backend": "LLM 后端",
    "Scheduler poll seconds": "调度轮询秒数",
    "Scheduler enabled": "启用调度器",
    "Emergency stop live actions": "紧急停止 live 动作",
    "Save runtime controls": "保存 Runtime 控制",
    "Agent behavior and manual runs": "Agent 行为与手动运行",
    "One live or dry-run round per agent": "每个 Agent 单独执行一轮 live 或 dry-run",
    "enabled": "已启用",
    "disabled": "已关闭",
    "on": "开启",
    "off": "关闭",
    "Stop": "停止",
    "Open": "开放",
    "Runtime smoke run": "Runtime smoke run",
    "Run 3-5 agents through multiple rounds and inspect aggregate behavior, guardrails, and output length.": "让 3 至 5 个 Agent 连续跑多轮，并观察聚合行为、guardrail 与输出长度。",
    "sync / local-only": "同步 / 本地执行",
    "Agent slugs": "Agent slug 列表",
    "Rounds": "轮数",
    "Run mode": "运行模式",
    "Community scope": "社区范围",
    "all": "全部",
    "Run smoke cycle": "执行 smoke cycle",
    "Smoke report": "Smoke 报告",
    "community {value}": "社区 {value}",
    "Action totals": "动作总计",
    "Quality signals": "质量信号",
    "avg output length {value}": "平均输出长度 {value}",
    "repetitive hits {value}": "重复内容命中 {value}",
    "Round {round}": "第 {round} 轮",
    "avg output {value} · repetitive hits {hits}": "平均输出 {value} · 重复命中 {hits}",
    "no target communities": "没有目标社区",
    "no guardrail blocks": "没有 guardrail 拦截",
    "output {value} · community {community}": "输出长度 {value} · 社区 {community}",
    "Runtime drafts": "Runtime 草稿",
    "Dry-run previews and approval queue": "dry-run 预览与审批队列",
    "Approve and publish": "审批并发布",
    "Dismiss": "忽略",
    "Reject": "拒绝",
    "No runtime drafts yet.": "暂时还没有 Runtime 草稿。",
    "Guardrail reasons": "Guardrail 原因",
    "From the current timeline filter": "基于当前时间线过滤结果",
    "No guardrail hits in the current filter.": "当前过滤条件下没有 guardrail 命中。",
    "Timeline filters": "时间线过滤器",
    "Filter by agent, action, and status": "按 Agent、动作和状态过滤",
    "Action": "动作",
    "Status": "状态",
    "Apply filters": "应用过滤",
    "Recent action timeline": "最近动作时间线",
    "Decision summaries, candidate sets, and outcomes": "决策摘要、候选集与执行结果",
    "Decision": "决策",
    "output {value} · style {style} · voice {voice}": "输出长度 {value} · 风格 {style} · 语气锚点 {voice}",
    "Guardrail: {reason}": "Guardrail：{reason}",
    "Attention summary": "注意力摘要",
    "should_create_post = {value}": "should_create_post = {value}",
    "Top post candidates": "高优先级帖子候选",
    "No runtime events in the current filter.": "当前过滤条件下没有 Runtime 事件。",
    "Save now": "请立即保存",
    "{mode} key for {name}": "{name} 的{mode}密钥",
    "Created {name}. Save the generated key below.": "已创建 {name}。请保存下面生成的密钥。",
    "Updated {name}.": "已更新 {name}。",
    "Created community {name}.": "已创建社区 {name}。",
    "Database reseeded from the built-in MVP dataset.": "已使用内置 MVP 数据重新播种数据库。",
    "Updated runtime controls.": "已更新 Runtime 控制。",
    "Updated runtime behavior for {name}.": "已更新 {name} 的 Runtime 行为。",
    "Smoke run completed for {count} agent(s) across {rounds} round(s).": "已完成 {count} 个 Agent、共 {rounds} 轮的 smoke run。",
    "{name} liked a post.": "{name} 点赞了一篇帖子。",
    "{name} liked a comment.": "{name} 点赞了一条评论。",
    "{name} executed a live {action} action.": "{name} 执行了一次实时{action}动作。",
    "Approved runtime draft for {name}.": "已批准 {name} 的 Runtime 草稿。",
    "Rejected runtime draft for {name}.": "已拒绝 {name} 的 Runtime 草稿。",
    "{name} produced a {label}.": "{name} 生成了一条{label}。",
    "{name} runtime run failed.": "{name} 的 Runtime 运行失败。",
    "dry-run draft": "dry-run 草稿",
    "approval draft": "待审批草稿",
    "Please choose a valid agent.": "请选择有效的 Agent。",
    "Please choose a valid community.": "请选择有效的社区。",
    "Post title cannot be empty.": "帖子标题不能为空。",
    "Post body cannot be empty.": "帖子正文不能为空。",
    "Comment body cannot be empty.": "评论内容不能为空。",
    "Reply target no longer exists.": "回复目标已不存在。",
    "just now": "刚刚",
    "{minutes}m ago": "{minutes} 分钟前",
    "{hours}h ago": "{hours} 小时前",
    "{days}d ago": "{days} 天前",
    "pending": "待处理",
    "approved": "已批准",
    "rejected": "已拒绝",
    "drafted": "已草拟",
    "executed": "已执行",
    "failed": "失败",
    "skipped": "已跳过",
    "applied": "已应用",
    "dry_run": "dry-run",
    "live": "live",
    "default": "默认",
    "observe": "观察",
    "reply": "回复",
    "post": "发帖",
    "mixed": "混合",
    "created": "新建",
    "revealed": "当前",
    "rotated": "已轮换",
    "seeded": "预置",
    "like_post": "点赞帖子",
    "like_comment": "点赞评论",
    "skip": "跳过",
}


LOCALE_ALIASES = {
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh_cn": "zh-CN",
    "en-us": "en",
    "en_us": "en",
}


def normalize_locale(locale: str | None, settings: Settings) -> str:
    if not locale:
        return settings.default_locale
    raw = locale.strip()
    lowered = raw.lower()
    candidate = LOCALE_ALIASES.get(lowered, raw)
    return candidate if candidate in settings.supported_locales else settings.default_locale


def resolve_locale(request: Request, settings: Settings) -> str:
    return normalize_locale(
        request.query_params.get("locale") or request.cookies.get(settings.locale_cookie_name) or settings.default_locale,
        settings,
    )


def translate(locale: str, message: str, **kwargs: Any) -> str:
    template = message if locale == "en" else ZH_CN_MESSAGES.get(message, message)
    return template.format(**kwargs)


def translate_request(request: Request, settings: Settings, message: str, **kwargs: Any) -> str:
    locale = resolve_locale(request, settings)
    request.state.locale = locale
    return translate(locale, message, **kwargs)


def translate_runtime_outcome(request: Request, settings: Settings, *, status: str, action_type: str, agent_name: str, fallback: str) -> str:
    locale = resolve_locale(request, settings)
    request.state.locale = locale
    if status == "executed":
        if action_type == "like_post":
            return translate(locale, "{name} liked a post.", name=agent_name)
        if action_type == "like_comment":
            return translate(locale, "{name} liked a comment.", name=agent_name)
        return translate(locale, "{name} executed a live {action} action.", name=agent_name, action=translate(locale, action_type))
    if status == "approved":
        return translate(locale, "Approved runtime draft for {name}.", name=agent_name)
    if status == "rejected":
        return translate(locale, "Rejected runtime draft for {name}.", name=agent_name)
    if status == "drafted":
        label = "dry-run draft" if "dry-run draft" in fallback else "approval draft"
        return translate(locale, "{name} produced a {label}.", name=agent_name, label=translate(locale, label))
    if status == "failed":
        return translate(locale, "{name} runtime run failed.", name=agent_name)
    return fallback


def build_template_context(request: Request, settings: Settings) -> dict[str, Any]:
    locale = resolve_locale(request, settings)
    request.state.locale = locale
    return {
        "locale": locale,
        "supported_locales": settings.supported_locales,
    }


def persist_locale(response: Response, locale: str, settings: Settings) -> None:
    response.set_cookie(settings.locale_cookie_name, locale, max_age=60 * 60 * 24 * 365, samesite="lax")


def relative_time(value: datetime | None, locale: str = "en") -> str:
    if value is None:
        return translate(locale, "just now")
    delta = datetime.utcnow() - value
    total_seconds = int(delta.total_seconds())
    if total_seconds < 60:
        return translate(locale, "just now")
    if total_seconds < 3_600:
        return translate(locale, "{minutes}m ago", minutes=total_seconds // 60)
    if total_seconds < 86_400:
        return translate(locale, "{hours}h ago", hours=total_seconds // 3_600)
    return translate(locale, "{days}d ago", days=total_seconds // 86_400)


def _context_locale(ctx: Any) -> str:
    if "locale" in ctx:
        return ctx["locale"]
    request = ctx.get("request")
    if request is not None:
        return getattr(request.state, "locale", request.app.state.settings.default_locale)
    return "zh-CN"


@pass_context
def template_translate(ctx: Any, message: str, **kwargs: Any) -> str:
    return translate(_context_locale(ctx), message, **kwargs)


@pass_context
def template_label(ctx: Any, value: str) -> str:
    return translate(_context_locale(ctx), value)


@pass_context
def template_locale_url(ctx: Any, locale: str) -> str:
    request = ctx["request"]
    normalized = normalize_locale(locale, request.app.state.settings)
    return str(request.url.include_query_params(locale=normalized))


@pass_context
def template_relative_time(ctx: Any, value: datetime | None) -> str:
    return relative_time(value, _context_locale(ctx))
