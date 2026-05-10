from __future__ import annotations

import json
import re

from openai import AsyncOpenAI

from .config import Config

_SYSTEM = """\
你是舞萌 DX B50 的视频口播锐评作者，不写报告，只写 OneCat 式锐评。
用户指定的语气、角度、问题优先级最高，先回应用户，再展开 B50；如果用户给了雌小鬼、玩机器、温柔、sunny_duck 等语气，要贯穿全文。
输出只要一整段中文口播，不换行，不要自我介绍、模型、来源、步骤、免责声明。

【工作流程】
先抓用户点名主题（如果有用户需求，就先解决用户需求）或本次最大爆点，再用 B35/B15、配置、同段对比、推分候选去验证，最后落到具体推分路线和具体谱名。不要固定按 rating、ARPI、首曲、配置、推分顺序念稿。

【字段翻译】
ds=定数；rating 和 ARPI 保留英文；achievement=达成率；peer_avg/avg_achievement=同段平均达成率；gap_vs_peer=比同段高多少；config_tags=配置词；community_vibe/chart_identity=大家都说/圈里常讲。
如果上下文里真的有 pc/play_count，再把它当游玩次数分析；如果没有，就不要硬提。

【分析规则】
B35 是旧版本/历史 best 35，看基本盘、下限、长期结构；B15 是当前版本/new best 15，看近期推分效率、上限突破、新版本适应。
100% 是鸟，100.5% 是鸟加，101% 是理论值；100.xx 是吃到分，99.xx 才叫没吃到分；100.5 附近不要催 AP。
13.0-13.5 算 13，13.6-13.9 算 13+，14.0-14.5 算 14，14.6-15.0 算 14+；gap_vs_peer > 0.8 按异常处理。
必须明确分析玩家擅长什么配置、为什么这么判断，至少点 2 张对应谱面；如果有同段统计，必须自然写 ARPI 和 gap。
正文必须落到具体证据：曲名、定数、达成率、song_rating、peer_avg/gap_vs_peer、B35/B15、配置词、强项/短板配置，至少点 3-5 张真实曲名。

【OneCat 口播提示词】
这是视频口播，不是分析报告。开头先裁决，再拆证据，再给建议。
要像现场锐评：短句、停顿、反问、先下结论。可以自然用家人们、你告诉我、有没有可能、就你看、那我只能说、虚低、重量级、变态、疯了、通透等词，但别堆成口号。
如果用户指定口吻/人设/文风，要整段都服从，不能只在开头装一下。
结尾一定要给具体推分路线和具体谱名，不能只说“还有提升空间”。

【硬性禁止】
不要写 markdown，不要写 ```json，不要写代码块外壳，不要写解释文字。
不要写 15k、16k、16000、16081 这类说法，rating 只叫 w5、w6、顶段，尽量结合 200 分细分段。
不要提 AP/FC 总数，也不要说没 AP、0 AP；不要把 100.xx 说成没吃到分。
不要写报告腔，不要堆“首先/其次/综上所述/整体来看”。
如果某项证据不存在，不要硬编。没有同段统计时，不要写 ARPI、gap、平均值结论。
只用真实曲名和真实配置词，禁止把不存在的配置词硬塞进去。

【风格收束】
title 是标题，10-18 字，必须带舞萌 DX 语境词。
overall_roast 是正文，一整段，不换行，建议 800-1100 字。
impression_roast 是一句总结，不超过 25 字。
输出严格 JSON，只保留 title、overall_roast、impression_roast 三个字段。
{style_instruction}"""


def _sanitize_rating_terms(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"(?<![A-Za-z0-9])16\s*[kK](?![A-Za-z0-9])", "w6", value)
    value = re.sub(r"(?<![A-Za-z0-9])15\s*[kK](?![A-Za-z0-9])", "w5", value)
    value = re.sub(r"(?<!\d)16[0-4]\d{2}(?!\d)", "w6", value)
    value = re.sub(r"(?<!\d)15\d{3}(?!\d)", "w5", value)
    value = re.sub(r"(?<!\d)1[7-9]\d{3}(?!\d)", "顶段", value)
    value = value.replace("```json", "").replace("```", "")
    return value


def _cleanup_response(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text, flags=re.I)
    try:
        data = json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return _sanitize_rating_terms(text)
        try:
            data = json.loads(m.group(0))
        except Exception:
            return _sanitize_rating_terms(text)

    cleaned = {
        "title": _sanitize_rating_terms(str(data.get("title") or "")).replace("\r", " ").replace("\n", " ").strip(),
        "overall_roast": _sanitize_rating_terms(str(data.get("overall_roast") or "")).replace("\r", " ").replace("\n", " ").strip(),
        "impression_roast": _sanitize_rating_terms(str(data.get("impression_roast") or "")).replace("\r", " ").replace("\n", " ").strip(),
    }
    return json.dumps(cleaned, ensure_ascii=False)


def _fmt(context: dict) -> str:
    player = context.get("player") or {}
    summary = context.get("summary") or {}
    peer = context.get("peer_stats") or {}
    pack = context.get("b50_evidence_pack") or {}

    lines = [
        f"玩家：{player.get('nickname')}  Rating：{player.get('rating')}",
        f"B35 RA：{summary.get('b35_ra')}  B15 RA：{summary.get('b15_ra')}",
        f"全B50平均达成：{summary.get('avg_achievement')}%  平均定数：{summary.get('avg_ds')}",
        f"B35均值：{(summary.get('b35') or {}).get('avg_achievement')}%  B15均值：{(summary.get('b15') or {}).get('avg_achievement')}%",
    ]

    arpi = peer.get("arpi")
    overlap = (peer.get("b50_overlap") or {}).get("value")
    if arpi is not None:
        lines.append(f"ARPI：{arpi:+.4f}  B50重合度：{overlap:.2f}%")

    peer_comp = pack.get("peer_comparison") or {}
    if peer_comp.get("matched") is not None:
        lines.append(f"同段匹配：{peer_comp.get('matched')}  同段桶：{peer_comp.get('rating_bucket')}")
    if peer_comp.get("available") is False:
        lines.append("同段统计：不可用时不要硬写 ARPI/gap")

    rating_split = pack.get("rating_split") or {}
    fine_segment = rating_split.get("fine_segment") or {}
    if fine_segment:
        lines.append(f"分段判断：{fine_segment.get('label')}  {fine_segment.get('tone')}")

    def _fmt_tags(tags: list) -> str:
        items = [str(t).strip() for t in (tags or []) if str(t).strip()]
        return "/".join(items[:4])

    def _chart_line(c: dict) -> str:
        gap = c.get("gap_vs_peer")
        peer_avg = c.get("peer_avg")
        tags = _fmt_tags(c.get("config_tags") or c.get("config") or [])
        parts = [f"[{c.get('bucket', '')} {c.get('ds', '')}] {c.get('title', '')}"]
        parts.append(f"{c.get('achievement', 0):.4f}%")
        parts.append(f"RA {c.get('song_rating', 0)}")
        if peer_avg is not None:
            parts.append(f"peer {peer_avg:.4f}%")
        if gap is not None:
            parts.append(f"gap {gap:+.4f}")
        if tags:
            parts.append(f"tags {tags}")
        return "  ".join(parts)

    config_focus = pack.get("config_focus") or {}
    picked = []
    for key in ("same_rating_average_entry_points", "selected_evidence", "strongest_vs_peer", "highest_song_rating"):
        for c in (pack.get(key) or [])[:3]:
            if c not in picked:
                picked.append(c)
            if len(picked) >= 6:
                break
        if len(picked) >= 6:
            break

    if config_focus.get("strong") or config_focus.get("weak"):
        lines.append("")
        lines.append("配置切入：")
        for item in (config_focus.get("strong") or [])[:3]:
            lines.append(f"  擅长 {item.get('tag')}：{item.get('count')} 张，均值 {item.get('avg_achievement')}%，gap {item.get('avg_gap_vs_peer')}")
        for item in (config_focus.get("weak") or [])[:2]:
            lines.append(f"  吃瘪 {item.get('tag')}：{item.get('count')} 张，均值 {item.get('avg_achievement')}%，gap {item.get('avg_gap_vs_peer')}")

    b35b15 = pack.get("b35_b15_structure") or {}
    if b35b15:
        lines.append("")
        lines.append("B35/B15：")
        for key in ("b35", "b15"):
            sec = b35b15.get(key) or {}
            if sec:
                lines.append(
                    f"  {key.upper()}：{sec.get('count')} 张，均值 {sec.get('avg_achievement')}%，RA {sec.get('avg_song_rating')}，gap {sec.get('avg_gap_vs_peer')}"
                )

    if picked:
        lines.append("")
        lines.append("关键谱：")
        lines.extend(_chart_line(c) for c in picked)

    for label, key in (
        ("同分入口", "same_rating_average_entry_points"),
        ("强证据", "strongest_vs_peer"),
        ("弱证据", "weakest_vs_peer"),
    ):
        rows = pack.get(key) or []
        if rows:
            lines.append("")
            lines.append(f"{label}：")
            for c in rows[:4]:
                pieces = [str(c.get("title") or "")]
                if c.get("ds") is not None:
                    pieces.append(f"ds {c.get('ds')}")
                if c.get("achievement") is not None:
                    pieces.append(f"ach {c.get('achievement'):.4f}%")
                if c.get("song_rating") is not None:
                    pieces.append(f"RA {c.get('song_rating')}")
                if c.get("peer_avg") is not None:
                    pieces.append(f"peer {c.get('peer_avg'):.4f}%")
                if c.get("gap_vs_peer") is not None:
                    pieces.append(f"gap {c.get('gap_vs_peer'):+.4f}")
                tag_text = _fmt_tags(c.get("config_tags") or c.get("config") or [])
                if tag_text:
                    pieces.append(f"tags {tag_text}")
                lines.append("  " + "  ".join(pieces))

    for label, key in (
        ("理论值/高光", "theory_cards"),
        ("15理论", "impossible_15_theory"),
        ("14+AP", "level_14_plus_ap"),
        ("高定数AP", "high_ds_ap"),
        ("异常gap", "abnormal_peer_gaps"),
    ):
        rows = pack.get(key) or []
        if rows:
            lines.append("")
            lines.append(f"{label}：")
            for c in rows[:4]:
                pieces = [str(c.get("title") or "")]
                if c.get("ds") is not None:
                    pieces.append(f"ds {c.get('ds')}")
                if c.get("achievement") is not None:
                    pieces.append(f"ach {c.get('achievement'):.4f}%")
                if c.get("song_rating") is not None:
                    pieces.append(f"RA {c.get('song_rating')}")
                if c.get("peer_avg") is not None:
                    pieces.append(f"peer {c.get('peer_avg'):.4f}%")
                if c.get("gap_vs_peer") is not None:
                    pieces.append(f"gap {c.get('gap_vs_peer'):+.4f}")
                lines.append("  " + "  ".join(pieces))

    ds_summary = pack.get("ds_band_summary") or {}
    if ds_summary:
        lines.append("")
        lines.append("定数段：")
        for band in ("<13", "13", "13+", "14", "14+"):
            item = ds_summary.get(band)
            if item:
                lines.append(
                    f"  {band}：均值 {item.get('avg_achievement')}% / gap {item.get('avg_gap_vs_peer')} / RA {item.get('avg_song_rating')}"
                )

    evidence = pack.get("selected_evidence") or []
    if evidence:
        lines.append("")
        lines.append("核心证据：")
        for c in evidence[:6]:
            pieces = [f"{c.get('title', '')}"]
            if c.get("ds") is not None:
                pieces.append(f"ds {c.get('ds')}")
            if c.get("achievement") is not None:
                pieces.append(f"ach {c.get('achievement'):.4f}%")
            if c.get("song_rating") is not None:
                pieces.append(f"RA {c.get('song_rating')}")
            if c.get("peer_avg") is not None:
                pieces.append(f"peer {c.get('peer_avg'):.4f}%")
            if c.get("gap_vs_peer") is not None:
                pieces.append(f"gap {c.get('gap_vs_peer'):+.4f}")
            tag_text = _fmt_tags(c.get("config_tags") or c.get("config") or [])
            if tag_text:
                pieces.append(f"tags {tag_text}")
            lines.append("  " + "  ".join(pieces))

    return "\n".join(lines)


async def generate_analysis(context: dict, config: Config, style: str = "") -> str:
    style_instruction = f"\n- 请用以下风格/语气/需求进行锐评：{style}" if style else ""
    system = _SYSTEM.format(style_instruction=style_instruction)

    client = AsyncOpenAI(
        api_key=config.b50_llm_key,
        base_url=config.b50_llm_url.rstrip("/"),
    )
    resp = await client.chat.completions.create(
        model=config.b50_llm_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": _fmt(context)},
        ],
        temperature=0.8,
        max_tokens=1600,
    )
    content = (resp.choices[0].message.content or "").strip()
    return _cleanup_response(content)
