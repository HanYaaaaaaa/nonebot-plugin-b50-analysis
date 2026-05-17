from __future__ import annotations

_RULES: dict[str, list[str]] = {
    "politics": [
        "习近平", "毛泽东", "邓小平", "江泽民", "胡锦涛",
        "六四", "天安门事件", "法轮功", "台独", "港独", "疆独", "藏独",
        "一党专政",
    ],
    "porn": [
        "色情", "黄片", "成人视频", "裸聊", "约炮", "性服务",
        "援交", "做爱", "自慰教程", "呦交", "萝莉控",
    ],
    "violence": [
        "炸弹制作", "制枪教程", "恐怖袭击", "极端组织",
        "血腥虐杀", "砍人教程", "自制武器", "爆炸物配方",
        "自杀方法", "如何杀人",
    ],
    "hate": [
        "民族歧视", "种族歧视", "性别歧视", "地域黑",
        "支那", "黑鬼", "死全家", "操你妈", "你妈死了",
        "去死吧",
    ],
    "prompt_injection": [
        "忽略上述指令", "忽略以上指令", "忽略之前的指令",
        "ignore previous", "ignore above", "system prompt",
        "扮演开发者模式", "开发者模式", "jailbreak", "DAN",
        "越狱模式", "绕过审核", "disregard instructions",
    ],
    "illegal": [
        "毒品交易", "冰毒购买", "大麻购买", "赌博网站",
        "诈骗教程", "洗钱教程", "盗号教程", "信用卡套现",
        "黑产教程", "网贷暴力催收",
    ],
}

_CATEGORY_REASONS = {
    "politics": "请求包含敏感政治内容，本次分析已驳回，请换个舞萌 DX 相关问题。",
    "porn": "请求包含色情低俗内容，本次分析已驳回，请换个健康的表达方式。",
    "violence": "请求包含暴力或危险内容，本次分析已驳回。",
    "hate": "请求包含攻击或歧视性内容，本次分析已驳回，请保持友好表达。",
    "prompt_injection": "检测到指令注入尝试，本次请求已驳回。",
    "illegal": "请求包含违法违规内容，本次分析已驳回。",
}

_KEYWORD_SETS: dict[str, set[str]] = {}


def _compile_rules() -> None:
    global _KEYWORD_SETS
    _KEYWORD_SETS = {
        category: {str(word).casefold() for word in words if str(word).strip()}
        for category, words in _RULES.items()
    }


def _scan(text: str) -> tuple[str | None, list[str]]:
    raw = str(text or "")
    if not raw:
        return None, []
    lowered = raw.casefold()
    for category, words in _KEYWORD_SETS.items():
        matched = [word for word in words if word and word in lowered]
        if matched:
            matched.sort(key=lambda x: (-len(x), x))
            return category, matched
    return None, []


def _display_matches(matches: list[str]) -> list[str]:
    return matches[:2]


def _redact(text: str, matches: list[str]) -> str:
    raw = str(text or "")
    if not raw or not matches:
        return raw
    lowered = raw.casefold()
    mask = [False] * len(raw)
    for word in sorted({m for m in matches if m}, key=len, reverse=True):
        start = 0
        while True:
            idx = lowered.find(word, start)
            if idx < 0:
                break
            end = min(idx + len(word), len(mask))
            for i in range(idx, end):
                mask[i] = True
            start = max(idx + 1, end)

    chunks: list[str] = []
    i = 0
    while i < len(raw):
        if not mask[i]:
            chunks.append(raw[i])
            i += 1
            continue
        chunks.append("***")
        while i < len(raw) and mask[i]:
            i += 1
    return "".join(chunks)


def check_user_input(text: str) -> dict:
    category, matched = _scan(text)
    if not category:
        return {"allowed": True, "category": None, "matched": [], "reason": ""}
    return {
        "allowed": False,
        "category": category,
        "matched": _display_matches(matched),
        "reason": _CATEGORY_REASONS.get(category, "请求包含不适合处理的内容，本次分析已驳回。"),
    }


def check_llm_output(text: str) -> dict:
    category, matched = _scan(text)
    if not category:
        return {"safe": True, "category": None, "redacted": str(text or "")}
    return {
        "safe": False,
        "category": category,
        "redacted": _redact(str(text or ""), matched),
    }


def add_keyword(category: str, word: str) -> None:
    cat = str(category or "").strip()
    kw = str(word or "").strip()
    if not cat or not kw:
        return
    _RULES.setdefault(cat, [])
    if kw not in _RULES[cat]:
        _RULES[cat].append(kw)
    _compile_rules()


def remove_keyword(category: str, word: str) -> None:
    cat = str(category or "").strip()
    kw = str(word or "").strip()
    if not cat or not kw or cat not in _RULES:
        return
    _RULES[cat] = [item for item in _RULES[cat] if item != kw]
    _compile_rules()


_compile_rules()
