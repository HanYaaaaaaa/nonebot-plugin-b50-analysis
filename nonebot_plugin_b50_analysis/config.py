from pydantic import BaseModel


class Config(BaseModel):
    """从 .env / .env.prod 读取的插件配置。"""

    b50_llm_url: str = "https://api.openai.com/v1"
    """OpenAI 兼容 API 的 base URL，末尾不带斜杠"""

    b50_llm_key: str = ""
    """API Key"""

    b50_llm_model: str = "gemini-3-flash-preview"
    """使用的模型名称"""

    b50_moderation_model: str = ""
    """内容审查使用的模型名称，不配置则不进行AI审查"""

    b50_assets_path: str = ""
    """assets 目录路径，包含 ui/fonts、ui/icons、peer_stats.zip 等素材（必填）"""

    b50_daily_limit: int = 0
    """每个用户每日最多调用次数，0 表示不限制"""

    maimaidxtoken: str = ""
    """水鱼开发者 token，配置后可获取完整游玩记录数据"""
