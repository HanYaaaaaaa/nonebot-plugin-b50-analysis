from __future__ import annotations

import io
import json
import math
import random
import re
from pathlib import Path
from typing import Any

import httpx

from .paths import DATA_DIR

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

CANVAS_W = 2000
DIFF_SHORT = {0: "BAS", 1: "ADV", 2: "EXP", 3: "MAS", 4: "ReM"}
FC_ICON = {
    "FC": "UI_MSS_MBase_Icon_FC.png",
    "FC+": "UI_MSS_MBase_Icon_FCp.png",
    "AP": "UI_MSS_MBase_Icon_AP.png",
    "AP+": "UI_MSS_MBase_Icon_APp.png",
}


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


def _strip(text: str) -> str:
    return re.sub(r"[\U00010000-\U0010ffff]", "", str(text or ""))


def _rank_icon(ach: float) -> str:
    for threshold, name in [
        (100.5, "SSSp"), (100.0, "SSS"), (99.5, "SSp"), (99.0, "SS"),
        (98.0, "Sp"), (97.0, "S"), (94.0, "AAA"), (90.0, "AA"), (80.0, "A"),
    ]:
        if ach >= threshold:
            return f"UI_TTR_Rank_{name}.png"
    return ""


def _ra_pic(rating: int) -> str:
    for threshold, name in [
        (1000, "01"), (2000, "02"), (4000, "03"), (7000, "04"), (10000, "05"),
        (12000, "06"), (13000, "07"), (14000, "08"), (14500, "09"), (15000, "10"),
    ]:
        if rating < threshold:
            return f"UI_CMN_DXRating_{name}.png"
    return "UI_CMN_DXRating_11.png"


def _parse_analysis_result(analysis: Any) -> dict:
    if isinstance(analysis, dict):
        raw = dict(analysis)
    else:
        text = str(analysis or "").strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text, flags=re.I)
        try:
            raw = json.loads(text)
        except Exception:
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                try:
                    raw = json.loads(m.group(0))
                except Exception:
                    raw = {}
            else:
                raw = {}
        if not raw:
            raw = {"title": "B50锐评", "overall_roast": text, "impression_roast": ""}

    title = _strip(str(raw.get("title") or "")).replace("\r", " ").replace("\n", " ").strip()
    overall = _strip(str(raw.get("overall_roast") or "")).replace("\r", " ").strip()
    impression = _strip(str(raw.get("impression_roast") or "")).replace("\r", " ").strip()
    overall = re.sub(r"\s*\n\s*", " ", overall)
    impression = re.sub(r"\s*\n\s*", " ", impression)
    if not title:
        title = "B50锐评"
    return {"title": title, "overall_roast": overall, "impression_roast": impression}


class _Draw:
    def __init__(self, data: dict, screen_title: str, analysis_result: dict, assets: Path) -> None:
        self.data = data
        self.screen_title = _strip(screen_title)
        self.analysis_title = _strip(str(analysis_result.get("title") or ""))
        self.analysis_overall = _strip(str(analysis_result.get("overall_roast") or ""))
        self.analysis_impression = _strip(str(analysis_result.get("impression_roast") or ""))
        self.assets = assets
        self.ui = assets / "ui"
        self.icons = self.ui / "icons"
        self.cover_cache_dir = DATA_DIR / "cache" / "covers"
        self.im = Image.new("RGBA", (CANVAS_W, 5800), (255, 255, 255, 255))
        self.d = ImageDraw.Draw(self.im)
        self.fonts: dict[str, Any] = {}
        self.covers: dict[str, Any] = {}
        self.avatar: Any = None

    def font(self, family: str, size: int) -> Any:
        key = f"{family}:{size}"
        if key not in self.fonts:
            fname = "SourceHanSansSC-Bold.otf" if family == "cn" else "Torus SemiBold.otf"
            self.fonts[key] = ImageFont.truetype(str(self.ui / "fonts" / fname), size)
        return self.fonts[key]

    def _ensure_h(self, min_h: int) -> None:
        if min_h <= self.im.height:
            return
        new_h = int(math.ceil(min_h / 200.0) * 200)
        new_im = Image.new("RGBA", (CANVAS_W, new_h), (255, 255, 255, 255))
        new_im.alpha_composite(self.im)
        self.im = new_im
        self.d = ImageDraw.Draw(self.im)

    def rrect(self, xy: tuple, radius: int, fill: Any, outline: Any = None) -> None:
        x1, y1, x2, y2 = (int(v) for v in xy)
        layer = Image.new("RGBA", (max(1, x2 - x1), max(1, y2 - y1)), (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle((0, 0, x2 - x1, y2 - y1), radius=radius, fill=fill, outline=outline)
        self.im.alpha_composite(layer, (x1, y1))
        self.d = ImageDraw.Draw(self.im)

    def paste(self, img: Any, xy: tuple) -> None:
        self.im.alpha_composite(img.convert("RGBA"), xy)
        self.d = ImageDraw.Draw(self.im)

    def icon(self, filename: str, size: tuple) -> Any:
        if not filename:
            return None
        path = self.icons / filename
        if not path.exists():
            return None
        try:
            return Image.open(path).convert("RGBA").resize(size, Image.Resampling.LANCZOS)
        except Exception:
            return None

    def wrap(self, text: str, font: Any, max_w: int) -> list[str]:
        lines: list[str] = []
        for raw in str(text or "").replace("\r", "").split("\n"):
            cur = ""
            for ch in raw:
                if font.getbbox(cur + ch)[2] > max_w:
                    if cur:
                        lines.append(cur)
                    cur = ch
                else:
                    cur += ch
            if cur:
                lines.append(cur)
        return lines

    def fit_line(self, text: str, max_w: int, max_sz: int = 28, min_sz: int = 16) -> tuple:
        clean = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
        for sz in range(max_sz, min_sz - 1, -2):
            f = self.font("cn", sz)
            if f.getbbox(clean)[2] <= max_w:
                return f, clean
        f = self.font("cn", min_sz)
        lo, hi = 0, len(clean)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if f.getbbox(clean[:mid] + "...")[2] <= max_w:
                lo = mid
            else:
                hi = mid - 1
        return f, clean if lo == len(clean) else clean[:lo] + "..."

    def fit_text(self, text: str, max_w: int, max_lines: int, max_sz: int = 28, min_sz: int = 16) -> tuple:
        for sz in range(max_sz, min_sz - 1, -2):
            f = self.font("cn", sz)
            lines = self.wrap(text, f, max_w)
            step = max(sz + 10, int(sz * 1.45))
            if len(lines) <= max_lines:
                return f, lines, step
        f = self.font("cn", min_sz)
        lines = self.wrap(text, f, max_w)[:max_lines]
        if lines and len(self.wrap(text, f, max_w)) > max_lines:
            lines[-1] = lines[-1].rstrip("。.，；") + "..."
        return f, lines, max(min_sz + 10, int(min_sz * 1.45))

    def load_cover(self, song_id: Any, size: int = 120) -> Any:
        sid = str(song_id or "")
        key = f"{sid}:{size}"
        if key in self.covers:
            return self.covers[key]
        self.cover_cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cover_cache_dir / f"{sid}.png"
        default = self.ui / "default_cover.png"
        try:
            img = Image.open(path if path.exists() else default).convert("RGBA")
        except Exception:
            img = Image.new("RGBA", (size, size), (200, 200, 200, 255))
        self.covers[key] = img.resize((size, size), Image.Resampling.LANCZOS)
        return self.covers[key]

    def load_avatar(self) -> None:
        qq = str((self.data.get("player") or {}).get("qq") or "")
        if not qq:
            return
        path = DATA_DIR / "cache" / "avatars" / f"{qq}.png"
        if not path.exists():
            return
        try:
            self.avatar = Image.open(path).resize((140, 140)).convert("RGBA")
        except Exception:
            self.avatar = None

    def draw_header(self) -> None:
        player = self.data.get("player") or {}
        peer = self.data.get("peer_stats") or {}
        summary = self.data.get("summary") or {}
        rating = _i(player.get("rating"))

        self.rrect((40, 30, 620, 420), 16, (245, 248, 255, 255))
        if self.avatar:
            mask = Image.new("L", (140, 140), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 140, 140), fill=255)
            circle = Image.new("RGBA", (140, 140), (0, 0, 0, 0))
            circle.paste(self.avatar, (0, 0), mask)
            self.paste(circle, (80, 50))
        nick = str(player.get("nickname") or player.get("username") or "maimai player")
        nf, nl = self.fit_line(nick, 330, 32, 20)
        self.d.text((240, 55), nl, font=nf, fill=(51, 51, 51))
        ra_img = self.icon(_ra_pic(rating), (108, 22))
        if ra_img:
            self.paste(ra_img, (240, 111))
        self.d.text((296, 108), f"{rating:05d}", font=self.font("en", 18), fill=(255, 255, 255))

        arpi = peer.get("arpi")
        overlap_val = (peer.get("b50_overlap") or {}).get("value")
        arpi_text = "N/A" if arpi is None else f"{_f(arpi):+.4f}"
        overlap_text = "N/A" if overlap_val is None else f"{_f(overlap_val):.2f}%"
        self.d.text((80, 250), "B35 / B15", font=self.font("en", 22), fill=(120, 120, 120))
        self.d.text((220, 242), f"{summary.get('b35_ra', 0)} / {summary.get('b15_ra', 0)}", font=self.font("en", 32), fill=(51, 51, 51))
        self.d.text((80, 310), "ARPI", font=self.font("en", 22), fill=(120, 120, 120))
        self.d.text((160, 300), arpi_text, font=self.font("en", 36), fill=(46, 125, 50) if _f(arpi, 0) >= 0 else (198, 40, 40))
        self.d.text((80, 360), "重合", font=self.font("cn", 22), fill=(120, 120, 120))
        self.d.text((160, 350), overlap_text, font=self.font("en", 36), fill=(66, 133, 244))

        self.rrect((640, 30, 1260, 420), 16, (245, 248, 255, 255))
        self.d.text((675, 55), "平均值", font=self.font("cn", 30), fill=(26, 115, 232))
        rows = [
            ("全B50达成", summary.get("avg_achievement"), "%"),
            ("全B50同段", summary.get("avg_peer"), "%"),
            ("B35均值", (summary.get("b35") or {}).get("avg_achievement"), "%"),
            ("B15均值", (summary.get("b15") or {}).get("avg_achievement"), "%"),
            ("定数均值", summary.get("avg_ds"), ""),
        ]
        y = 110
        for label, value, suffix in rows:
            txt = "N/A" if value is None else f"{_f(value):.4f}{suffix}" if suffix else f"{_f(value):.2f}"
            self.d.text((675, y), label, font=self.font("cn", 22), fill=(110, 110, 110))
            self.d.text((850, y - 8), txt, font=self.font("en", 30), fill=(51, 51, 51))
            y += 55

        self.rrect((1280, 30, 1960, 420), 16, (255, 251, 235, 255), (245, 221, 160, 255))
        self.d.text((1310, 52), "指数说明", font=self.font("cn", 28), fill=(180, 110, 20))
        explain = (
            "ARPI：对比同 rating 段玩家在同一谱面的平均达成率，得到综合表现差异。"
            "B50重合度：统计同段玩家 B50 与本 B50 的平均重合比例。"
            "低于30%偏小众审美，超过50%偏模板路线；高分段重合度仅作娱乐参考。"
        )
        f, lines, step = self.fit_text(explain, 620, 7, 24, 18)
        for i, line in enumerate(lines):
            self.d.text((1310, 100 + i * step), line, font=f, fill=(95, 85, 65))
        slogan = "分析内容仅供娱乐参考，不要攀比和焦虑，玩得开心就好。"
        f2, lines2, step2 = self.fit_text(slogan, 620, 2, 22, 18)
        for i, line in enumerate(lines2):
            self.d.text((1310, 325 + i * step2), line, font=f2, fill=(198, 40, 40))

    def song_card(self, x: int, y: int, w: int, h: int, song: dict, label: str, lc: Any, bg: Any, show_peer: bool = False) -> None:
        self.rrect((x, y, x + w, y + h), 14, bg)
        mid = song.get("music_id") or song.get("musicId") or ""
        self.paste(self.load_cover(mid, 120), (x + 15, y + 15))
        self.d.text((x + 15, y + h - 30), label, font=self.font("cn", 18), fill=lc)
        tf, title = self.fit_line(str(song.get("title") or ""), 760, 24, 18)
        self.d.text((x + 150, y + 12), title, font=tf, fill=(51, 51, 51))
        ach = _f(song.get("achievement"))
        ach_text = f"{ach:.4f}%"
        self.d.text((x + 150, y + 45), ach_text, font=self.font("en", 48), fill=(33, 33, 33))
        ix = x + 150 + self.font("en", 48).getbbox(ach_text)[2] + 12
        rank = self.icon(_rank_icon(ach), (80, 40))
        if rank:
            self.paste(rank, (ix, y + 55))
            ix += 88
        fc_img = self.icon(FC_ICON.get(str(song.get("fc_label") or ""), ""), (50, 50))
        if fc_img:
            self.paste(fc_img, (ix, y + 50))
        level_idx = _i(song.get("level_index"), -1)
        ds = _f(song.get("ds"))
        info_y = y + 108
        self.d.text((x + 150, info_y), f"{DIFF_SHORT.get(level_idx, '')} {ds:.1f}", font=self.font("en", 22), fill=(140, 140, 140))
        self.d.text((x + 420, info_y), f"RA {_i(song.get('ra'))}", font=self.font("en", 22), fill=(232, 124, 32))
        if song.get("overlap") is not None:
            self.d.text((x + 680, info_y), f"重合 {_f(song.get('overlap')):.2f}%", font=self.font("cn", 20), fill=(66, 133, 244))
        row2_y = y + 135
        if show_peer and song.get("peer_avg") is not None:
            self.d.text((x + 150, row2_y), f"同级均值 {_f(song.get('peer_avg')):.4f}%", font=self.font("cn", 20), fill=(120, 120, 120))
            if song.get("gap") is not None:
                gap = _f(song.get("gap"))
                self.d.text((x + 430, row2_y), f"ARPI {gap:+.4f}", font=self.font("en", 20), fill=(46, 125, 50) if gap >= 0 else (198, 40, 40))
        row3_y = y + 162
        chart_summaries = self.data.get("chart_summaries") or {}
        summary = chart_summaries.get(str(mid)) or {}
        config_tags = summary.get("config_tags") or song.get("config_tags") or song.get("config") or song.get("keywords") or []
        if config_tags:
            tag_x = x + 150
            for tag in config_tags[:5]:
                tag_str = str(tag).strip()
                if not tag_str:
                    continue
                tag_font = self.font("cn", 17)
                tw = tag_font.getbbox(tag_str)[2] + 12
                if tag_x + tw > x + w - 10:
                    break
                self.rrect((tag_x, row3_y, tag_x + tw, row3_y + 24), 6, (220, 235, 255, 255))
                self.d.text((tag_x + 6, row3_y + 3), tag_str, font=tag_font, fill=(30, 100, 200))
                tag_x += tw + 6

    def draw_sections(self) -> int:
        evidence = self.data.get("evidence") or {}
        cy = 450
        card_h = 210
        sections = [
            ("亮点谱面", "highlights", "亮点", (46, 125, 50), (232, 245, 233, 255), True, 4),
            ("普通点", "ordinaries", "普通", (198, 40, 40), (253, 237, 237, 255), True, 2),
            ("单曲RA最高", "highest_song_rating", "最高RA", (232, 124, 32), (255, 248, 235, 255), False, 1),
            ("B50重合极值", "overlap_extremes", "重合", (66, 133, 244), (235, 245, 255, 255), False, 2),
            ("推分推荐", "push_recommendations", "推分", (232, 124, 32), (255, 248, 235, 255), False, 3),
            ("配置特化", "config_specialized", "擅长", (30, 100, 180), (230, 240, 255, 255), False, 2),
            ("最少游玩", "least_played", "少PC", (120, 80, 200), (240, 235, 255, 255), False, 2),
        ]
        for title, key, label, color, bg, show_peer, max_n in sections:
            songs = (evidence.get(key) or self.data.get(key) or [])[:max_n]
            if not songs:
                continue
            self.d.text((40, cy), title, font=self.font("cn", 28), fill=color)
            cy += 38
            for row_start in range(0, len(songs), 2):
                for col in range(2):
                    idx = row_start + col
                    if idx >= len(songs):
                        break
                    self.song_card(40 + col * 980, cy, 940, card_h, songs[idx], label, color, bg, show_peer)
                cy += card_h + 15
        return cy

    def draw_analysis(self, start_y: int) -> int:
        top_y = start_y + 45
        body_font, body_lines, body_step = self.fit_text(self.analysis_overall, 1780, 999, 26, 15)
        summary_font, summary_lines, summary_step = self.fit_text(self.analysis_impression, 1780, 3, 24, 16)
        body_h = max(420, 84 + len(body_lines) * body_step + 80)
        summary_h = 0
        if self.analysis_impression:
            summary_h = max(150, 76 + len(summary_lines) * summary_step + 48)
        panel_h = body_h + summary_h + (24 if summary_h else 0)
        self._ensure_h(top_y + panel_h + 160)
        self.d.text((40, start_y), "B50锐评", font=self.font("cn", 32), fill=(26, 115, 232))
        self.rrect((40, top_y, 1960, top_y + panel_h), 16, (250, 252, 255, 255))
        if self.analysis_title:
            self.d.text((70, top_y + 22), self.analysis_title, font=self.font("cn", 34), fill=(26, 115, 232))

        body_y = top_y + 84
        self.rrect((70, body_y, 1930, body_y + body_h), 14, (255, 249, 238, 255), (245, 210, 150, 255))
        self.d.text((90, body_y + 14), "正文", font=self.font("cn", 28), fill=(198, 100, 20))
        y_cur = body_y + 62
        for line in body_lines:
            self.d.text((90, y_cur), line, font=body_font, fill=(80, 65, 45))
            y_cur += body_step

        if self.analysis_impression:
            summary_y = body_y + body_h + 24
            self.rrect((70, summary_y, 1930, summary_y + summary_h), 14, (245, 248, 255, 255), (210, 225, 245, 255))
            self.d.text((90, summary_y + 14), "总结", font=self.font("cn", 26), fill=(26, 115, 232))
            y_cur = summary_y + 52
            for line in summary_lines:
                self.d.text((90, y_cur), line, font=summary_font, fill=(80, 80, 80))
                y_cur += summary_step
        return top_y + panel_h + 20

    def draw_footer(self, y: int) -> None:
        text = "Designed by HanYa@OneCatBot"
        f = self.font("en", 24)
        tw = f.getbbox(text)[2]
        self.d.text(((CANVAS_W - tw) // 2, y), text, font=f, fill=(180, 140, 80))

    def draw(self) -> Any:
        random.seed(7)
        self.load_avatar()
        self.draw_header()
        songs_end = self.draw_sections()
        panel_end = self.draw_analysis(songs_end + 10)
        self._ensure_h(panel_end + 140)
        self.draw_footer(panel_end + 10)
        cropped = self.im.crop((0, 0, CANVAS_W, panel_end + 100))
        out_w = 1000
        out_h = int(out_w * cropped.height / cropped.width)
        return cropped.resize((out_w, out_h), Image.Resampling.LANCZOS).convert("RGB")


async def prepare_render_cache(context: dict) -> None:
    """异步预下载头像和曲绘，避免渲染阶段阻塞事件循环。"""
    if not context:
        return

    avatar_dir = DATA_DIR / "cache" / "avatars"
    cover_dir = DATA_DIR / "cache" / "covers"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    cover_dir.mkdir(parents=True, exist_ok=True)

    urls: list[tuple[str, Path]] = []
    qq = str((context.get("player") or {}).get("qq") or "")
    if qq:
        avatar_path = avatar_dir / f"{qq}.png"
        if not avatar_path.exists():
            urls.append((f"http://q.qlogo.cn/headimg_dl?dst_uin={qq}&spec=640", avatar_path))

    seen: set[str] = set()
    for song in context.get("b50") or []:
        sid = str(song.get("music_id") or song.get("musicId") or "")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        cover_path = cover_dir / f"{sid}.png"
        if cover_path.exists():
            continue
        try:
            sid_int = int(sid)
        except ValueError:
            continue
        urls.append((f"https://www.diving-fish.com/covers/{sid_int:05d}.png", cover_path))

    if not urls:
        return

    async with httpx.AsyncClient(timeout=8) as client:
        for url, path in urls:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                path.write_bytes(resp.content)
            except Exception:
                continue


def render_image(context: dict, analysis_text: str, assets_path: str) -> Any:
    """渲染分析图，失败时抛出异常。"""
    if not _PIL_OK:
        raise RuntimeError("Pillow 未安装，请执行 pip install Pillow")
    if not assets_path:
        raise RuntimeError("未配置 b50_assets_path，请在 .env 中填写 assets 目录路径")
    assets = Path(assets_path)
    font_dir = assets / "ui" / "fonts"
    if not font_dir.exists():
        raise RuntimeError(f"assets 目录下未找到字体文件夹：{font_dir}")
    player = context.get("player") or {}
    title = f"{player.get('nickname', '')} B50锐评"
    analysis_result = _parse_analysis_result(analysis_text)
    drawer = _Draw(context, title, analysis_result, assets)
    return drawer.draw()
