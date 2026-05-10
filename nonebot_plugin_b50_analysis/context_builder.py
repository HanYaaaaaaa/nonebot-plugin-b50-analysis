from __future__ import annotations

import gzip
import json
import zipfile
from pathlib import Path
from typing import Any

FC_LABEL_MAP = {"fc": "FC", "fcp": "FC+", "ap": "AP", "app": "AP+"}


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _i(v: Any, d: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def _load_file(p: Path) -> dict | None:
    try:
        if p.suffix == ".zip":
            with zipfile.ZipFile(p) as zf:
                name = next(n for n in zf.namelist() if n.endswith(".json"))
                return json.loads(zf.read(name))
        if p.suffix == ".gz":
            with gzip.open(p) as f:
                return json.loads(f.read())
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_json(assets: Path, *parts: str) -> dict | list | None:
    p = assets.joinpath(*parts)
    if not p.exists():
        return None
    return _load_file(p)


def load_peer_stats(assets_path: str) -> dict | None:
    """从 assets 目录自动查找 peer_stats 文件。"""
    if not assets_path:
        return None
    assets = Path(assets_path)
    for name in ("peer_stats.zip", "peer_stats.json.gz", "peer_stats.json"):
        p = assets / name
        if p.exists():
            return _load_file(p)
    return None


def _normalize(chart: dict) -> dict:
    c = dict(chart)
    c["music_id"] = str(c.get("song_id") or c.get("music_id") or "")
    c["achievement"] = _f(c.get("achievements") or c.get("achievement"))
    c["fc_label"] = FC_LABEL_MAP.get(str(c.get("fc") or "").lower(), "")
    return c


def _fine_rating_segment(rating: int) -> dict:
    if rating >= 16500:
        return {
            "label": "16500+ 顶级门槛段",
            "range": "16500+",
            "tone": "按顶段尺度评价，不要按普通 w6 轻描淡写。",
        }
    if rating >= 15000:
        start = (rating // 200) * 200
        return {
            "label": f"{start}-{start + 199} 细分段",
            "range": f"{start}-{start + 199}",
            "tone": "按 200 分细分段评价，不要只粗暴说 w5/w6。",
        }
    if rating >= 13500:
        start = (rating // 200) * 200
        return {
            "label": f"{start}-{start + 199} 上升段",
            "range": f"{start}-{start + 199}",
            "tone": "按 200 分细分段评价，重点看基本盘和推分空间。",
        }
    return {"label": "入门-进阶段", "range": "<13500", "tone": "以基础能力和推分空间为主。"}


def _ds_class(ds: float) -> str:
    if ds >= 14.6:
        return "14+"
    if ds >= 14.0:
        return "14"
    if ds >= 13.6:
        return "13+"
    if ds >= 13.0:
        return "13"
    return "<13"


def _gap_tier(gap: float | None) -> str:
    if gap is None:
        return ""
    if gap > 0.8:
        return "异常领先"
    if gap >= 0.5:
        return "明显领先"
    if gap < -0.8:
        return "异常落后"
    if gap <= -0.5:
        return "明显落后"
    return ""


def _song_evidence_row(chart: dict, chart_summaries: dict | None, rank: int) -> dict:
    gap = chart.get("gap")
    avg_achievement = chart.get("peer_avg")
    ds = _f(chart.get("ds"))
    achievement = _f(chart.get("achievement"))
    summary = (chart_summaries or {}).get(str(chart.get("music_id") or "")) or {}
    row = {
        "rank": rank,
        "music_id": str(chart.get("music_id") or ""),
        "title": str(chart.get("title") or ""),
        "bucket": chart.get("bucket"),
        "chart_type": chart.get("type") or chart.get("chart_type"),
        "level_label": chart.get("level_label"),
        "ds": ds,
        "ds_class": _ds_class(ds),
        "achievement": round(achievement, 4),
        "avg_achievement": round(_f(avg_achievement), 4) if avg_achievement is not None else None,
        "peer_avg": round(_f(avg_achievement), 4) if avg_achievement is not None else None,
        "gap": round(_f(gap), 4) if gap is not None else None,
        "gap_vs_peer": round(_f(gap), 4) if gap is not None else None,
        "gap_tier": _gap_tier(_f(gap)) if gap is not None else "",
        "song_rating": _i(chart.get("ra")),
        "fc_label": str(chart.get("fc_label") or ""),
        "is_ap": str(chart.get("fc_label") or "").upper() in {"AP", "AP+"},
        "config_tags": [str(x) for x in (summary.get("config_tags") or [])[:5]],
        "is_theory": achievement >= 101.0,
        "is_ap_target_reasonable": achievement >= 100.8,
        "overlap": chart.get("overlap"),
        "peer_sample_count": chart.get("peer_sample_count"),
    }
    return {k: v for k, v in row.items() if v not in (None, "", [])}


def _unique_rows(rows: list[dict], limit: int) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    result: list[dict] = []
    for row in rows:
        key = (str(row.get("music_id") or ""), str(row.get("level_label") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
        if len(result) >= limit:
            break
    return result


def _section_summary(rows: list[dict], label: str) -> dict:
    gaps = [_f(r.get("gap_vs_peer")) for r in rows if r.get("gap_vs_peer") is not None]
    peers = [_f(r.get("avg_achievement")) for r in rows if r.get("avg_achievement") is not None]
    by_rating_desc = sorted(rows, key=lambda r: _i(r.get("song_rating")), reverse=True)
    by_rating_asc = sorted(rows, key=lambda r: _i(r.get("song_rating")))
    by_gap = sorted([r for r in rows if r.get("gap_vs_peer") is not None], key=lambda r: _f(r.get("gap_vs_peer")), reverse=True)
    return {
        "label": label,
        "count": len(rows),
        "role": "旧版本/历史 best 35，看基本盘、下限和长期结构" if label == "B35" else "当前版本/new best 15，看新版本适应、上限突破和近期推分效率",
        "avg_ds": round(sum(_f(r.get("ds")) for r in rows if _f(r.get("ds")) > 0) / len([r for r in rows if _f(r.get("ds")) > 0]), 2) if any(_f(r.get("ds")) > 0 for r in rows) else None,
        "avg_achievement": round(sum(_f(r.get("achievement")) for r in rows if _f(r.get("achievement")) > 0) / len([r for r in rows if _f(r.get("achievement")) > 0]), 4) if any(_f(r.get("achievement")) > 0 for r in rows) else None,
        "avg_peer_achievement": round(sum(peers) / len(peers), 4) if peers else None,
        "avg_gap_vs_peer": round(sum(gaps) / len(gaps), 4) if gaps else None,
        "avg_song_rating": round(sum(_f(r.get("song_rating")) for r in rows if _f(r.get("song_rating")) > 0) / len([r for r in rows if _f(r.get("song_rating")) > 0]), 1) if any(_f(r.get("song_rating")) > 0 for r in rows) else None,
        "top_cards": by_rating_desc[:5],
        "floor_cards": by_rating_asc[:5],
        "best_peer_gaps": by_gap[:4],
        "worst_peer_gaps": list(reversed(by_gap[-4:])),
    }


def _build_b50_evidence_pack(charts: list[dict], rating: int, peer_data: dict, chart_summaries: dict | None = None) -> dict:
    rows = [_song_evidence_row(c, chart_summaries, idx + 1) for idx, c in enumerate(charts)]
    rows_by_rating = sorted(rows, key=lambda r: _i(r.get("song_rating")), reverse=True)
    rows_with_gap = sorted([r for r in rows if r.get("gap_vs_peer") is not None], key=lambda r: _f(r.get("gap_vs_peer")), reverse=True)
    b35 = [r for r in rows if r.get("bucket") == "B35"]
    b15 = [r for r in rows if r.get("bucket") == "B15"]
    ds_bands: dict[str, list[dict]] = {}
    for row in rows:
        ds_bands.setdefault(str(row.get("ds_class") or "<13"), []).append(row)

    ds_summary = {
        band: {
            "count": len(items),
            "avg_achievement": round(sum(_f(x.get("achievement")) for x in items if _f(x.get("achievement")) > 0) / len([x for x in items if _f(x.get("achievement")) > 0]), 4) if any(_f(x.get("achievement")) > 0 for x in items) else None,
            "avg_peer_achievement": round(sum(_f(x.get("avg_achievement")) for x in items if x.get("avg_achievement") is not None) / len([x for x in items if x.get("avg_achievement") is not None]), 4) if any(x.get("avg_achievement") is not None for x in items) else None,
            "avg_gap_vs_peer": round(sum(_f(x.get("gap_vs_peer")) for x in items if x.get("gap_vs_peer") is not None) / len([x for x in items if x.get("gap_vs_peer") is not None]), 4) if any(x.get("gap_vs_peer") is not None for x in items) else None,
            "avg_song_rating": round(sum(_f(x.get("song_rating")) for x in items if _f(x.get("song_rating")) > 0) / len([x for x in items if _f(x.get("song_rating")) > 0]), 1) if any(_f(x.get("song_rating")) > 0 for x in items) else None,
        }
        for band, items in ds_bands.items()
    }

    strongest = rows_with_gap[:8]
    weakest = list(reversed(rows_with_gap[-8:]))
    selected = _unique_rows(strongest[:4] + weakest[:4] + rows_by_rating[:4], 10)
    entry_points = _unique_rows(strongest[:6] + weakest[:6], 10)

    return {
        "peer_comparison": {
            "available": bool(peer_data),
            "rating_bucket": peer_data.get("bucket"),
            "matched": peer_data.get("matched", 0),
            "ARPI": peer_data.get("arpi"),
            "b50_overlap": peer_data.get("b50_overlap") or {},
            "rule": "peer_avg/avg_achievement 是同 rating 桶玩家在同一谱同一难度的平均达成率；gap_vs_peer=当前达成率-peer_avg；ARPI 是所有可匹配 B50 谱面的平均 gap。",
        },
        "rating_split": {
            "total": rating,
            "fine_segment": _fine_rating_segment(rating),
            "b35_ra": sum(_i(r.get("song_rating")) for r in b35),
            "b15_ra": sum(_i(r.get("song_rating")) for r in b15),
            "top10_avg_song_rating": round(sum(_f(r.get("song_rating")) for r in rows_by_rating[:10]) / len(rows_by_rating[:10]), 1) if rows_by_rating[:10] else None,
            "bottom10_avg_song_rating": round(sum(_f(r.get("song_rating")) for r in sorted(rows, key=lambda r: _i(r.get("song_rating")))[:10]) / len(sorted(rows, key=lambda r: _i(r.get("song_rating")))[:10]), 1) if rows else None,
        },
        "b35_b15_structure": {
            "rule": "B35 是旧版本/历史 best 35，主要看基本盘、下限、长期结构；B15 是当前版本/new best 15，主要看新版本适应、上限突破、近期推分效率。",
            "b35": _section_summary(b35, "B35"),
            "b15": _section_summary(b15, "B15"),
        },
        "ds_band_summary": ds_summary,
        "config_focus": _build_config_focus(rows),
        "same_rating_average_entry_points": entry_points,
        "selected_evidence": selected,
        "strongest_vs_peer": strongest,
        "weakest_vs_peer": weakest,
        "abnormal_peer_gaps": [r for r in rows_with_gap if str(r.get("gap_tier") or "").startswith("异常")][:8],
        "highest_song_rating": rows_by_rating[:8],
        "b50_floor": sorted(rows, key=lambda r: _i(r.get("song_rating")))[:8],
        "theory_cards": [r for r in rows_by_rating if r.get("is_theory")][:8],
        "impossible_15_theory": [r for r in rows_by_rating if _f(r.get("ds")) >= 15.0 and r.get("is_theory")][:4],
        "high_ds_ap": [r for r in rows_by_rating if r.get("is_ap") and _f(r.get("ds")) >= 14.0][:8],
        "level_14_plus_ap": [r for r in rows_by_rating if r.get("is_ap") and _f(r.get("ds")) >= 14.6][:6],
        "mid_ds_high_gap": [r for r in rows_by_rating if 13.0 <= _f(r.get("ds")) < 14.6 and _f(r.get("gap_vs_peer")) >= 0.25][:8],
    }




def _build_config_focus(rows: list[dict]) -> dict:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        tags = row.get("config_tags") or []
        for tag in tags[:4]:
            t = str(tag).strip()
            if not t:
                continue
            groups.setdefault(t, []).append(row)
    strong: list[dict] = []
    weak: list[dict] = []
    for tag, items in groups.items():
        avg_ach = sum(_f(x.get("achievement")) for x in items if _f(x.get("achievement")) > 0) / len([x for x in items if _f(x.get("achievement")) > 0]) if any(_f(x.get("achievement")) > 0 for x in items) else 0.0
        avg_gap = sum(_f(x.get("gap_vs_peer")) for x in items if x.get("gap_vs_peer") is not None) / len([x for x in items if x.get("gap_vs_peer") is not None]) if any(x.get("gap_vs_peer") is not None for x in items) else 0.0
        entry = {"tag": tag, "count": len(items), "avg_achievement": round(avg_ach, 4), "avg_gap_vs_peer": round(avg_gap, 4)}
        if len(items) >= 2 and avg_ach >= 100.3:
            strong.append(entry)
        elif len(items) >= 2 and avg_ach < 100.0:
            weak.append(entry)
    strong.sort(key=lambda x: (-x["avg_achievement"], -x["count"]))
    weak.sort(key=lambda x: (x["avg_achievement"], -x["count"]))
    return {"strong": strong[:5], "weak": weak[:5]}

def _load_assets_context(assets_path: str) -> dict:
    if not assets_path:
        return {}
    assets = Path(assets_path)
    kb = _load_json(assets, "kb", "mai_knowledge.json") or {}
    roast = _load_json(assets, "kb", "roast_memory.json") or {}
    chart_summary = _load_json(assets, "chart_summary.json") or {}
    music_data = _load_json(assets, "music_data.json") or {}
    return {
        "kb": kb,
        "roast_memory": roast,
        "chart_summary": chart_summary,
        "music_data": music_data,
    }


def build_context(b50_data: dict, peer_stats: dict | None = None) -> dict:
    player = {
        "nickname": b50_data.get("nickname") or b50_data.get("username") or "maimai player",
        "username": b50_data.get("username") or "",
        "rating": _i(b50_data.get("rating")),
        "qq": str(b50_data.get("qq") or ""),
    }

    sd = [_normalize(c) for c in ((b50_data.get("charts") or {}).get("sd") or [])[:35]]
    dx = [_normalize(c) for c in ((b50_data.get("charts") or {}).get("dx") or [])[:15]]
    all_charts = sd + dx

    assets_ctx = _load_assets_context(str(b50_data.get("_assets_path") or ""))

    if not all_charts:
        return {"player": player, "peer_stats": {}, "summary": {}, "evidence": {}, "b50": [], **assets_ctx}

    b35_ra = sum(_i(c.get("ra")) for c in sd)
    b15_ra = sum(_i(c.get("ra")) for c in dx)
    avg_ach = sum(c["achievement"] for c in all_charts) / len(all_charts)
    avg_ds = sum(_f(c.get("ds")) for c in all_charts) / len(all_charts)
    b35_avg = sum(c["achievement"] for c in sd) / len(sd) if sd else 0.0
    b15_avg = sum(c["achievement"] for c in dx) / len(dx) if dx else 0.0

    peer_data: dict = {}
    if peer_stats:
        rating = player["rating"]
        sz = _i(peer_stats.get("rating_bucket_size"), 200)
        lo = (rating // sz) * sz
        bucket = (peer_stats.get("buckets") or {}).get(f"{lo}-{lo + sz - 1}") or {}
        chart_stats = bucket.get("charts") or {}
        if chart_stats:
            gaps, overlaps = [], []
            for c in all_charts:
                key = f"{c['music_id']}:{_i(c.get('level_index'), -1)}"
                stat = chart_stats.get(key)
                if stat:
                    avg = _f(stat.get("avg_achievement"))
                    gap = c["achievement"] - avg
                    appear = _f(stat.get("b50_appear_rate"))
                    if appear <= 1:
                        appear *= 100
                    c["peer_avg"] = avg
                    c["gap"] = gap
                    c["overlap"] = appear
                    gaps.append(gap)
                    overlaps.append(appear)
            if gaps:
                peer_data = {
                    "available": True,
                    "bucket": f"{lo}-{lo + sz - 1}",
                    "matched": len(gaps),
                    "arpi": round(sum(gaps) / len(gaps), 4),
                    "b50_overlap": {"value": round(sum(overlaps) / len(overlaps), 2)},
                }

    with_gap = [c for c in all_charts if c.get("gap") is not None]
    highlights = sorted(with_gap, key=lambda c: c.get("gap", 0), reverse=True)[:4]
    ordinaries = sorted(with_gap, key=lambda c: c.get("gap", 0))[:2]
    highest_ra = sorted(all_charts, key=lambda c: _i(c.get("ra")), reverse=True)[:1]
    overlap_extremes: list[dict] = []
    if with_gap:
        hi = max(with_gap, key=lambda c: c.get("overlap", 0))
        lo_c = min(with_gap, key=lambda c: c.get("overlap", 100))
        overlap_extremes = [hi, lo_c] if hi is not lo_c else [hi]

    summary = {
        "b35_ra": b35_ra,
        "b15_ra": b15_ra,
        "avg_achievement": round(avg_ach, 4),
        "avg_ds": round(avg_ds, 2),
        "b35": {"avg_achievement": round(b35_avg, 4)},
        "b15": {"avg_achievement": round(b15_avg, 4)},
    }
    if peer_data.get("arpi") is not None and with_gap:
        summary["avg_peer"] = round(
            sum(c.get("peer_avg", 0) for c in with_gap) / len(with_gap), 4
        )
        summary["avg_gap"] = round(
            sum(c.get("gap", 0) for c in with_gap) / len(with_gap), 4
        )

    chart_summaries = assets_ctx.get("chart_summary") or {}
    evidence_pack = _build_b50_evidence_pack(all_charts, player["rating"], peer_data, chart_summaries)
    config_focus = evidence_pack.get("config_focus") or {}

    return {
        "player": player,
        "peer_stats": peer_data,
        "summary": summary,
        "evidence": {
            "highlights": highlights,
            "ordinaries": ordinaries,
            "highest_song_rating": highest_ra,
            "overlap_extremes": overlap_extremes,
            "same_rating_average_entry_points": evidence_pack.get("same_rating_average_entry_points", []),
            "selected_evidence": evidence_pack.get("selected_evidence", []),
        },
        "b50_evidence_pack": evidence_pack,
        "config_focus": config_focus,
        "b50": all_charts,
        "chart_summaries": chart_summaries,
        **assets_ctx,
    }
