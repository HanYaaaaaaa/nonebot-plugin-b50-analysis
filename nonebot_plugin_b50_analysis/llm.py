from __future__ import annotations

import json
import re

from openai import AsyncOpenAI

from .config import Config

_FORBIDDEN_OUTPUT_PATTERNS = [
    "综上所述", "整体来看", "值得称赞", "值得一提", "由此可见", "不难看出",
    "毋庸置疑", "首先", "其次", "与其说", "不如说",
    "w5低", "w5中", "w5高", "w6低", "w6中", "w6高", "15k", "16k",
    "AP数量", "AP 数量", "AP总数", "AP 总数", "FC数量", "FC 数量", "FC总数", "FC 总数",
    "没有 AP", "没 AP", "0 AP", "AP 挂零", "没有AP", "没AP",
]

_SUNNY_STYLE_MARKERS = [
    "OneCat", "家人们", "你告诉我", "有没有可能", "就你看", "那我只能说", "某种程度上",
    "虚低", "割裂", "榜样", "开香槟", "通透", "伟大", "变态", "疯了", "固若金汤",
    "瞻仰", "重量级", "我人直接傻", "是真看不懂", "咱就说", "一点毛病没有", "保守", "吃透",
    "匹配不到一块", "营养美味", "众生百态", "直接给你封", "重点表扬",
]

_SUNNY_PRAISE_MARKERS = [
    "伟大", "变态", "疯了", "榜样", "开香槟", "固若金汤", "重量级", "瞻仰",
    "通透", "吃透", "行业标杆", "淋漓尽致", "我人直接傻", "是真看不懂",
]

_SUNNY_SPOKEN_MARKERS = [
    "你告诉我", "有没有可能", "那我只能说", "就你看", "咱就说", "嘶", "哎", "对吧", "是吧",
]

_SUNNY_SHOW_MARKERS = [
    "家人们", "瞻仰", "我人直接傻", "是真看不懂", "开香槟", "重量级",
    "往下一滑", "结果你这一看", "这就有味", "直接给你封", "重点表扬",
]

_REPORT_TONE_TERMS = [
    "说明", "结构", "匹配", "健康", "综合来看", "分析可见", "数据表明", "整体表现",
]


def _fine_rating_segment(rating) -> dict:
    try:
        r = int(rating or 0)
    except (TypeError, ValueError):
        r = 0
    if r >= 16500:
        return {
            "label": "16500+ 顶级门槛段",
            "range": "16500+",
            "tone": "这已经是普通玩家视角里的顶级分段，必须明显抬高评价尺度，不能按普通 w6 轻描淡写。",
        }
    if r >= 15000:
        band_start = (r // 200) * 200
        band_end = band_start + 199
        return {
            "label": f"{band_start}-{band_end} 细分段",
            "range": f"{band_start}-{band_end}",
            "tone": "按 200 分细分段评价，不要只粗暴说 w5/w6。",
        }
    if r >= 13500:
        band_start = (r // 200) * 200
        band_end = band_start + 199
        return {
            "label": f"{band_start}-{band_end} 上升段",
            "range": f"{band_start}-{band_end}",
            "tone": "按 200 分细分段评价。",
        }
    return {"label": "入门-进阶段", "range": "<13500", "tone": "以基础能力和推分空间为主。"}


_SYSTEM = """\
你是舞萌 DX B50 的视频口播锐评作者，不写报告，只写 OneCat 式锐评。
用户指定的语气、角度、问题优先级最高，先回应用户，再展开 B50；如果用户给了雌小鬼、玩机器、温柔、sunny_duck 等语气，要贯穿全文。
输出只要一整段中文口播，不换行，不要自我介绍、模型、来源、步骤、免责声明。

【工作流程】
先抓用户点名主题（如果有用户需求，就先解决用户需求）或本次最大爆点，再用 B35/B15、配置、同段对比、推分候选去验证，最后落到具体推分路线和具体谱名。不要固定按 rating、ARPI、首曲、配置、推分顺序念稿。

【字段翻译铁律】
ds=定数；rating 和 ARPI 保留英文；achievement=达成率；peer_avg/avg_achievement=同段平均达成率；gap_vs_peer=比同段高多少；config_tags=配置词；community_vibe/chart_identity=大家都说/圈里常讲；overlap/b50_overlap=B50 重合度；chart_type=具体颜色（绿/黄/红/紫/白谱）；play_count/pc=游玩次数。
禁止直接吐 peer_avg/gap_vs_peer/config_tags/overlap/community_vibe/chart_identity/chart_type/play_count 这些英文原变量名——必须翻译成中文。只有 ARPI/rating/B35/B15/FC/AP 可以保留英文。
如果上下文里真的有 pc/play_count，再把它当游玩次数分析；如果没有，就不要硬提。

【分析规则】
B35 是旧版本/历史 best 35，看基本盘、下限、长期结构；B15 是当前版本/new best 15，看近期推分效率、上限突破、新版本适应。
100% 是鸟，100.5% 是鸟加，101% 是理论值；100.xx 是吃到分，99.xx 才叫没吃到分；100.5 附近不要催 AP。
13.0-13.5 算 13，13.6-13.9 算 13+，14.0-14.5 算 14，14.6-15.0 算 14+；gap_vs_peer > 0.8 按异常处理。
必须明确分析玩家擅长什么配置、为什么这么判断，至少点 2 张对应谱面；如果有同段统计，必须自然写 ARPI 和 gap。
正文必须落到具体证据：曲名、定数、达成率、song_rating、peer_avg/gap_vs_peer、B35/B15、配置词、强项/短板配置，至少点 3-5 张真实曲名。
rating 不到 15000 却出现 14+，尤其 15.0 理论值，和常规进度严重不匹配，应直接从 rating 视角判为虚低/恐怖/世界未解之谜级。
B50 重合度：低于 30%=选曲小众/口味独到/谱面含金量高（正面评价）；30-50% 正常；高于 50% 偏模板/跟风攻略。不能只报数字不解读。单曲重合度低的谱更值得夸「这张大家没几个打，你啃下来了」。
ARPI 同段对比：sufficient=True 时按 position 判断（above_p75=同段上四分位/稳手，around_median=典型画风，below_p25=下四分位/靠选谱拉分）；sufficient=False 时说「同段样本还不够，先不硬下判断」。绝对禁止自己编同段 ARPI 数值。
config_profile：strong 是达成率 ≥100.3 且出现 ≥2 次的擅长配置（必须点名表扬）；weak 是达成率 <100.0 且出现 ≥2 次的短板配置（必须温和指出）。每次锐评至少点 1 个 strong + 1 个 weak（数据存在时），不允许空泛说「配置均衡」。
push_recommendations 字段已给出推分推荐，每条带 strategy_tag 和 reason，照搬说法即可；不要自己另编一套推分曲目，结尾必须落到具体谱名。
将牌=98/99/100% 对应铜将/银将/金将；神牌=100.5%（银神）/101%（理论神/金神）。B50 里的 101 理论值谱可顺带说「这张是理论神」。

【OneCat 口播提示词】
这是视频口播，不是分析报告。开头先裁决，再拆证据，再给建议。
要像现场锐评：短句、停顿、反问、先下结论。可以自然用家人们、你告诉我、有没有可能、就你看、那我只能说、虚低、重量级、变态、疯了、通透等词，但别堆成口号。
如果用户指定口吻/人设/文风，要整段都服从，不能只在开头装一下。
结尾一定要给具体推分路线和具体谱名，不能只说"还有提升空间"。
必须至少有 1 个强夸赞词（伟大/变态/疯了/榜样/开香槟/固若金汤/重量级/瞻仰/通透/吃透）、1 个反问式口播句（你告诉我/有没有可能/那我只能说/就你看）、1 个节目效果转场（家人们/我们一起来瞻仰一下/我人直接傻了/这是真看不懂/换我已经开香槟了/往下一滑更重量级/结果你这一看）。
rating 必须按 200 分细分段看，尤其 16500+ 是顶级门槛段，语气和判断尺度必须明显抬高，不能只粗暴说 w6。
夸赞必须具体到数据：夸 B35 地板固若金汤、B15 新版本适应重量级、某张谱打得通透、某个定数被吃透、某个同段差距直接溢出。不要只写"很强"。
community_vibe/chart_identity（诈骗谱/神谱/练习谱…）是圈子里大家的看法，能自然融入一句「大家都说这是诈骗谱」「圈里公认练习向」最好。
SD 谱=标准谱（note 数较少、接近经典 maimai），DX 谱（引入大量 touch、密度更高）。讲 touch 交互/内外屏配合时天然指向 DX 谱，讲 tap/slide 经典配置时指向 SD 谱。

【硬性禁止】
不要写 markdown，不要写 ```json，不要写代码块外壳，不要写解释文字。
不要写 15k、16k、16000、16081 这类说法，rating 只叫 w5、w6、顶段，尽量结合 200 分细分段。
不要提 AP/FC 总数，也不要说没 AP、0 AP；不要把 100.xx 说成没吃到分。
不要写报告腔，不要堆"首先/其次/综上所述/整体来看"。
如果某项证据不存在，不要硬编。没有同段统计时，不要写 ARPI、gap、平均值结论。
只用真实曲名和真实配置词，禁止把不存在的配置词硬塞进去。
禁止固定自我介绍开头（如「亲爱的玩家，你好，我是正能量主播OneCat」）。
禁止使用「综上所述/整体来看/值得称赞/值得一提/由此可见/不难看出/毋庸置疑/首先/其次」。
禁止使用「w5低/w5中/w5高/w6低/w6中/w6高」细分称呼。
禁止报 AP/FC 总数，禁止说没 AP、0 AP、AP 挂零。
禁止使用「不是 X，而是 Y」「与其说 X，不如说 Y」这种对仗模板，同类句式全文最多 1 次。
禁止使用「提款机」「印钞机」「火箭」这类脱离舞萌数据的泛比喻撑内容。

【风格收束】
title 是标题，10-18 字，必须带舞萌 DX 语境词（rating 段/鸟/定数/AP/配置词/谱面类型等舞萌黑话，禁止无关形容词如「咖啡色的梦」「秋天的萤火虫」）。
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

    rating_val = player.get("rating")
    fine_seg = _fine_rating_segment(rating_val)

    lines = [
        f"玩家：{player.get('nickname')}  Rating：{rating_val}",
        f"分段判断：{fine_seg.get('label')}  {fine_seg.get('tone')}",
        f"B35 RA：{summary.get('b35_ra')}  B15 RA：{summary.get('b15_ra')}",
        f"全B50平均达成：{summary.get('avg_achievement')}%  平均定数：{summary.get('avg_ds')}",
        f"B35均值：{(summary.get('b35') or {}).get('avg_achievement')}%  B15均值：{(summary.get('b15') or {}).get('avg_achievement')}%",
    ]

    arpi = peer.get("arpi")
    overlap = (peer.get("b50_overlap") or {}).get("value")
    if arpi is not None:
        lines.append(f"ARPI：{arpi:+.4f}  B50重合度：{overlap:.2f}%")

    # ARPI bucket stats
    arpi_bucket = context.get("arpi_bucket_stats") or {}
    if arpi_bucket.get("sufficient"):
        pos = arpi_bucket.get("position", "")
        pos_label = {"above_p75": "同段上四分位/稳手", "around_median": "典型画风", "below_p25": "下四分位/靠选谱拉分"}.get(pos, pos)
        lines.append(f"ARPI同段位置：{pos_label}  均值：{arpi_bucket.get('mean')}  中位：{arpi_bucket.get('median')}")
    elif arpi_bucket:
        lines.append("ARPI同段：样本不足，先不硬下判断")

    # B50 overlap interpretation
    b50_overlap = context.get("b50_overlap") or {}
    if isinstance(b50_overlap, dict) and b50_overlap.get("value") is not None:
        ov = float(b50_overlap.get("value") or 0)
        if ov < 30:
            ov_desc = "选曲小众/口味独到/谱面含金量高（正面）"
        elif ov <= 50:
            ov_desc = "正常区间"
        else:
            ov_desc = "偏模板/跟风攻略"
        lines.append(f"B50重合度：{ov:.2f}%  解读：{ov_desc}")

    peer_comp = pack.get("peer_comparison") or {}
    if peer_comp.get("matched") is not None:
        lines.append(f"同段匹配：{peer_comp.get('matched')}  同段桶：{peer_comp.get('rating_bucket')}")
    if peer_comp.get("available") is False:
        lines.append("同段统计：不可用时不要硬写 ARPI/gap")

    rating_split = pack.get("rating_split") or {}
    fine_segment = rating_split.get("fine_segment") or {}
    if fine_segment:
        lines.append(f"分段判断（pack）：{fine_segment.get('label')}  {fine_segment.get('tone')}")

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
            parts.append(f"同段均值 {peer_avg:.4f}%")
        if gap is not None:
            parts.append(f"同段差距 {gap:+.4f}")
        if tags:
            parts.append(f"配置 {tags}")
        return "  ".join(parts)

    # Config profile (strong/weak)
    config_profile = context.get("config_profile") or {}
    if config_profile.get("strong") or config_profile.get("weak"):
        lines.append("")
        lines.append("配置画像：")
        for item in (config_profile.get("strong") or [])[:3]:
            kw = item.get("kw") or item.get("tag") or ""
            cnt = item.get("count", 0)
            avg = item.get("avg_ach") or item.get("avg_achievement") or 0
            lines.append(f"  擅长 {kw}：{cnt} 张，均值 {avg}%")
        for item in (config_profile.get("weak") or [])[:2]:
            kw = item.get("kw") or item.get("tag") or ""
            cnt = item.get("count", 0)
            avg = item.get("avg_ach") or item.get("avg_achievement") or 0
            lines.append(f"  短板 {kw}：{cnt} 张，均值 {avg}%")

    config_focus = pack.get("config_focus") or {}
    if config_focus.get("strong") or config_focus.get("weak"):
        lines.append("")
        lines.append("配置切入：")
        for item in (config_focus.get("strong") or [])[:3]:
            lines.append(f"  擅长 {item.get('tag')}：{item.get('count')} 张，均值 {item.get('avg_achievement')}%，同段差距 {item.get('avg_gap_vs_peer')}")
        for item in (config_focus.get("weak") or [])[:2]:
            lines.append(f"  吃瘪 {item.get('tag')}：{item.get('count')} 张，均值 {item.get('avg_achievement')}%，同段差距 {item.get('avg_gap_vs_peer')}")

    b35b15 = pack.get("b35_b15_structure") or {}
    if b35b15:
        lines.append("")
        lines.append("B35/B15：")
        for key in ("b35", "b15"):
            sec = b35b15.get(key) or {}
            if sec:
                lines.append(
                    f"  {key.upper()}：{sec.get('count')} 张，均值 {sec.get('avg_achievement')}%，RA {sec.get('avg_song_rating')}，同段差距 {sec.get('avg_gap_vs_peer')}"
                )

    picked = []
    for key in ("same_rating_average_entry_points", "selected_evidence", "strongest_vs_peer", "highest_song_rating"):
        for c in (pack.get(key) or [])[:3]:
            if c not in picked:
                picked.append(c)
            if len(picked) >= 6:
                break
        if len(picked) >= 6:
            break

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
                    pieces.append(f"定数 {c.get('ds')}")
                if c.get("achievement") is not None:
                    pieces.append(f"达成率 {c.get('achievement'):.4f}%")
                if c.get("song_rating") is not None:
                    pieces.append(f"RA {c.get('song_rating')}")
                if c.get("peer_avg") is not None:
                    pieces.append(f"同段均值 {c.get('peer_avg'):.4f}%")
                if c.get("gap_vs_peer") is not None:
                    pieces.append(f"同段差距 {c.get('gap_vs_peer'):+.4f}")
                tag_text = _fmt_tags(c.get("config_tags") or c.get("config") or [])
                if tag_text:
                    pieces.append(f"配置 {tag_text}")
                lines.append("  " + "  ".join(pieces))

    for label, key in (
        ("理论值/高光", "theory_cards"),
        ("15理论", "impossible_15_theory"),
        ("14+AP", "level_14_plus_ap"),
        ("高定数AP", "high_ds_ap"),
        ("异常同段差距", "abnormal_peer_gaps"),
    ):
        rows = pack.get(key) or []
        if rows:
            lines.append("")
            lines.append(f"{label}：")
            for c in rows[:4]:
                pieces = [str(c.get("title") or "")]
                if c.get("ds") is not None:
                    pieces.append(f"定数 {c.get('ds')}")
                if c.get("achievement") is not None:
                    pieces.append(f"达成率 {c.get('achievement'):.4f}%")
                if c.get("song_rating") is not None:
                    pieces.append(f"RA {c.get('song_rating')}")
                if c.get("peer_avg") is not None:
                    pieces.append(f"同段均值 {c.get('peer_avg'):.4f}%")
                if c.get("gap_vs_peer") is not None:
                    pieces.append(f"同段差距 {c.get('gap_vs_peer'):+.4f}")
                lines.append("  " + "  ".join(pieces))

    ds_summary = pack.get("ds_band_summary") or {}
    if ds_summary:
        lines.append("")
        lines.append("定数段：")
        for band in ("<13", "13", "13+", "14", "14+"):
            item = ds_summary.get(band)
            if item:
                lines.append(
                    f"  {band}：均值 {item.get('avg_achievement')}% / 同段差距 {item.get('avg_gap_vs_peer')} / RA {item.get('avg_song_rating')}"
                )

    evidence = pack.get("selected_evidence") or []
    if evidence:
        lines.append("")
        lines.append("核心证据：")
        for c in evidence[:6]:
            pieces = [f"{c.get('title', '')}"]
            if c.get("ds") is not None:
                pieces.append(f"定数 {c.get('ds')}")
            if c.get("achievement") is not None:
                pieces.append(f"达成率 {c.get('achievement'):.4f}%")
            if c.get("song_rating") is not None:
                pieces.append(f"RA {c.get('song_rating')}")
            if c.get("peer_avg") is not None:
                pieces.append(f"同段均值 {c.get('peer_avg'):.4f}%")
            if c.get("gap_vs_peer") is not None:
                pieces.append(f"同段差距 {c.get('gap_vs_peer'):+.4f}")
            tag_text = _fmt_tags(c.get("config_tags") or c.get("config") or [])
            if tag_text:
                pieces.append(f"配置 {tag_text}")
            lines.append("  " + "  ".join(pieces))

    # Push recommendations
    push_recs = context.get("push_recommendations") or []
    if push_recs:
        lines.append("")
        lines.append("推分推荐（直接引用，不要另编）：")
        for r in push_recs[:4]:
            tag = r.get("strategy_tag") or ""
            reason = r.get("reason") or r.get("recommend_reason") or ""
            lines.append(f"  [{tag}] {r.get('title', '')}  定数 {r.get('ds', '')}  {reason}")

    # Chart summaries (community_vibe / chart_identity)
    chart_summaries = context.get("chart_summaries") or {}
    if chart_summaries:
        lines.append("")
        lines.append("大家的评价（community_vibe/chart_identity，自然融入「大家都说」）：")
        for title, s in list(chart_summaries.items())[:6]:
            if not isinstance(s, dict):
                continue
            vibe = s.get("community_vibe") or s.get("chart_identity") or ""
            tags = _fmt_tags(s.get("config_tags") or [])
            if vibe or tags:
                lines.append(f"  {title}：{vibe}  配置 {tags}")

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
