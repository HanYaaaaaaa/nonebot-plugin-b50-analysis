from __future__ import annotations

import io
import json
import asyncio

from nonebot import get_driver, get_plugin_config, on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata

from .config import Config
from .context_builder import build_context, load_peer_stats
from .daily_limit import get_today_usage, increment_usage, reset_user
from .fetch import fetch_player_data, init_music_data
from .llm import generate_analysis
from .moderation import check_llm_output, check_user_input
from .render import prepare_render_cache, render_image

__plugin_meta__ = PluginMetadata(
    name="B50分析",
    description="舞萌DX B50数据分析，生成锐评文本和分析图",
    homepage="https://github.com/HanYaaaaaaa/nonebot-plugin-b50-analysis",
    usage=(
        "分析b50          —— 默认风格分析自己的B50\n"
        "分析b50 [风格/需求]  —— 用指定风格或需求分析自己的B50\n"
        "示例：分析b50 用可爱的语气"
    ),
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

_cfg = get_plugin_config(Config)
_peer_stats = load_peer_stats(_cfg.b50_assets_path)

driver = get_driver()

_active_tasks: dict[str, asyncio.Task] = {}
ANALYSIS_TIMEOUT = 60


@driver.on_startup
async def _startup():
    await init_music_data()    


async def _release_lock(qq: str):
    if qq in _active_tasks:
        del _active_tasks[qq]


b50_cmd = on_command(
    "分析b50",
    aliases={"b50分析", "分析B50", "B50分析"},
    priority=5,
    block=True,
)


async def _run_analysis(matcher: Matcher, event: MessageEvent, style: str):
    qq = event.get_user_id()
    
    limit = _cfg.b50_daily_limit
    if limit > 0 and qq not in get_driver().config.superusers:
        used = get_today_usage(qq)
        if used >= limit:
            await matcher.finish(f"已经上限了哦，每天 {limit} 次，明天再来吧~")
            return

    await matcher.send("正在查询 B50，请稍候…")

    if style:
        mod_result = await check_user_input(style)
        if not mod_result.get("allowed", True):
            if limit > 0 and qq not in get_driver().config.superusers:
                increment_usage(qq)
            await matcher.finish(mod_result.get("reason", "请求包含不适合处理的内容，本次分析已驳回（消耗使用次数）"))
            return

    try:
        b50_data = await fetch_player_data(qq)
    except ValueError as e:
        await matcher.finish(str(e))
        return
    except Exception:
        await matcher.finish("查询失败，请稍后重试")
        return

    b50_data["_assets_path"] = _cfg.b50_assets_path
    context = build_context(b50_data, _peer_stats)
    context["player"]["qq"] = qq

    if not _cfg.b50_llm_key:
        await matcher.finish("未配置 b50_llm_key，请在 .env 中填写 API Key")
        return

    try:
        analysis_text = await generate_analysis(context, _cfg, style)
    except Exception as e:
        await matcher.finish(f"分析生成失败：{e}")
        return

    # 直接解析JSON结果，不进行输出审查
    try:
        _parsed = json.loads(analysis_text)
        if isinstance(_parsed.get("push_recommendations"), list):
            context.setdefault("evidence", {})["push_recommendations"] = _parsed.get("push_recommendations") or []
    except Exception:
        pass

    try:
        await prepare_render_cache(context, _cfg.b50_assets_path)
        img = render_image(context, analysis_text, _cfg.b50_assets_path)
    except Exception as e:
        await matcher.finish(f"制图失败：{e}")
        return

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    if limit > 0 and qq not in get_driver().config.superusers:
        increment_usage(qq)
    await matcher.finish(MessageSegment.image(buf))


@b50_cmd.handle()
async def _handle(matcher: Matcher, event: MessageEvent, args: Message = CommandArg()):
    style = args.extract_plain_text().strip()
    qq = event.get_user_id()

    # 检查是否正在进行分析
    if qq in _active_tasks:
        await matcher.finish("您正在进行分析，请稍等完成后再试~")
        return

    # 创建任务并添加到活动任务列表
    task = asyncio.create_task(_run_analysis(matcher, event, style))
    _active_tasks[qq] = task

    try:
        # 设置超时
        await asyncio.wait_for(task, timeout=ANALYSIS_TIMEOUT)
    except asyncio.TimeoutError:
        pass
    finally:
        # 无论成功还是失败，都释放锁
        await _release_lock(qq)


b50_reset_cmd = on_command(
    "重置分析次数",
    aliases={"重置分析"},
    priority=5,
    block=True,
)


@b50_reset_cmd.handle()
async def _handle_reset(matcher: Matcher, event: MessageEvent, args: Message = CommandArg()):
    if event.get_user_id() not in get_driver().config.superusers:
        await matcher.finish("超级用户才可以使用哦")
        return

    raw = args.extract_plain_text().strip()
    target_qq = ""

    if raw:
        target_qq = raw
    else:
        for seg in event.message:
            if seg.type == "at":
                target_qq = str(seg.data.get("qq", ""))
                break

    if not target_qq or target_qq == "all":
        await matcher.finish("请指定要重置的用户QQ号或@用户")
        return

    reset_user(target_qq)
    await matcher.finish(f"已重置用户 {target_qq} 的今日B50分析次数")
