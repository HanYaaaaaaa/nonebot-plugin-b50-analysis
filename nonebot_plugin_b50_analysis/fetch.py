from __future__ import annotations

import json
from typing import Any
from pathlib import Path

import httpx
import aiofiles
from nonebot import get_plugin_config
from nonebot.log import logger

from .config import Config

WATER_FISH_BASE = "https://www.diving-fish.com/api/maimaidxprober"

_cfg = get_plugin_config(Config)
_music_data_cache: list[dict] | None = None


def _load_env_token() -> str:
    root = Path(__file__).resolve().parent.parent
    for name in (".env.prod", ".env"):
        path = root / name
        if not path.exists():
            continue
        try:
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip().upper() != "MAIMAIDXTOKEN":
                    continue
                return value.strip().strip('"').strip("'")
        except Exception:
            continue
    return ""


def _get_dev_token() -> str:
    token = (_cfg.maimaidxtoken or "").strip()
    if token:
        return token
    return _load_env_token().strip()


async def init_music_data() -> None:
    global _music_data_cache
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{WATER_FISH_BASE}/music_data")
            resp.raise_for_status()
            _music_data_cache = resp.json()
            logger.info("获取到水鱼数据了捏")
            return
    except Exception as e:
        logger.warning(f"从 API 加载曲库失败: {e}")

    # API 失败，尝试从本地 assets 加载
    try:
        assets_path = Path(__file__).parent / "assets" / "music_data.json"
        if assets_path.exists():
            async with aiofiles.open(assets_path, 'r', encoding='utf-8') as f:
                _music_data_cache = json.loads(await f.read())
                logger.info("已从本地 assets 加载曲库数据")
                return
    except Exception as e:
        logger.error(f"加载本地曲库数据失败: {e}")
    
    _music_data_cache = None


def get_music_lookup() -> dict[str, dict] | None:
    """获取已缓存的曲库查找表，无数据时返回 None。"""
    if not _music_data_cache:
        return None
    lookup: dict[str, dict] = {}
    for m in _music_data_cache:
        mid = str(m.get("id") or "")
        if mid:
            lookup[mid] = m
    return lookup or None


async def fetch_player_data(qq: str) -> dict:
    # 尝试使用开发者 API
    dev_token = _get_dev_token()
    if dev_token:
        result = await _fetch_dev_records(qq, dev_token)
        if result is not None:
            return result
    return await _fetch_public_b50(qq)


async def _fetch_public_b50(qq: str) -> dict:
    """通过公开 API POST /query/player 获取 B50。"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{WATER_FISH_BASE}/query/player",
            json={"qq": int(qq), "b50": True},
        )
    if resp.status_code == 400:
        raise ValueError(f"用户不存在或未开放 B50 查询（QQ: {qq}）")
    if resp.status_code == 403:
        raise ValueError(f"该用户已关闭公开查询（QQ: {qq}）")
    resp.raise_for_status()
    return resp.json()


async def _fetch_dev_records(qq: str, dev_token: str) -> dict | None:
    """通过开发者 API 获取全量记录，按 version 分类后全量返回。"""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(
                f"{WATER_FISH_BASE}/dev/player/records",
                params={"qq": int(qq)},
                headers={"developer-token": dev_token},
            )
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception:
        return None

    records = data.get("records") or []
    if not records:
        return None

    lookup = get_music_lookup()
    old, new = _sort_old_new(records, lookup)
    total_ra = sum(_i(c.get("ra")) for c in old) + sum(_i(c.get("ra")) for c in new)
    return {
        "nickname": str(data.get("nickname") or f"Player({qq})"),
        "rating": _i(data.get("rating")) or total_ra,
        "charts": {"sd": old, "dx": new},
    }


_NEW_VERSION_POOL = {
    "maimai でらっくす PRiSM PLUS"
}


def _is_new(music_id: str, lookup: dict[str, dict] | None = None) -> bool:
    if not lookup:
        return False
    m = lookup.get(music_id)
    if not m:
        return False
    # 优先使用 basic_info 中的版本信息
    version = str(m.get("basic_info", {}).get("from", "") or m.get("from", ""))
    return version in _NEW_VERSION_POOL


def _sort_old_new(records: list[dict], lookup: dict[str, dict] | None = None) -> tuple[list[dict], list[dict]]:
    old, new = [], []
    for c in records:
        mid = str(c.get("song_id") or c.get("music_id") or "")
        is_n = _is_new(mid, lookup)
        c["is_new"] = is_n
        if is_n:
            new.append(c)
        else:
            old.append(c)
    old.sort(key=lambda x: _i(x.get("ra")), reverse=True)
    new.sort(key=lambda x: _i(x.get("ra")), reverse=True)
    return old, new


def _i(v: Any, d: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return d
