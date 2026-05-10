from __future__ import annotations

import io

from nonebot import get_plugin_config, on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata

from .config import Config
from .context_builder import build_context, load_peer_stats
from .fetch import fetch_b50
from .llm import generate_analysis
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

b50_cmd = on_command(
    "分析b50",
    aliases={"b50分析", "分析B50", "B50分析"},
    priority=5,
    block=True,
)


@b50_cmd.handle()
async def _handle(matcher: Matcher, event: MessageEvent, args: Message = CommandArg()):
    style = args.extract_plain_text().strip()
    qq = event.get_user_id()

    await matcher.send("正在查询 B50，请稍候…")

    try:
        b50_data = await fetch_b50(qq)
    except ValueError as e:
        await matcher.finish(str(e))
        return
    except Exception:
        await matcher.finish("查询失败，请稍后重试")
        return

    b50_data["_assets_path"] = _cfg.b50_assets_path
    context = build_context(b50_data, _peer_stats)
    # 把实际使用的 QQ 写回 player，供头像拉取使用
    context["player"]["qq"] = qq

    if not _cfg.b50_llm_key:
        await matcher.finish("未配置 b50_llm_key，请在 .env 中填写 API Key")
        return

    try:
        analysis_text = await generate_analysis(context, _cfg, style)
    except Exception as e:
        await matcher.finish(f"分析生成失败：{e}")
        return

    try:
        await prepare_render_cache(context)
        img = render_image(context, analysis_text, _cfg.b50_assets_path)
    except Exception as e:
        await matcher.finish(f"制图失败：{e}")
        return

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    await matcher.finish(MessageSegment.image(buf))
