import httpx


async def fetch_b50(qq: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://www.diving-fish.com/api/maimaidxprober/query/player",
            json={"qq": int(qq), "b50": True},
        )
    if resp.status_code == 400:
        raise ValueError(f"用户不存在或未开放 B50 查询（QQ: {qq}）")
    if resp.status_code == 403:
        raise ValueError(f"该用户已关闭公开查询（QQ: {qq}）")
    resp.raise_for_status()
    return resp.json()
