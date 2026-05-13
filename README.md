# nonebot-plugin-b50-analysis

<div align="center">

[![PyPI](https://img.shields.io/pypi/v/nonebot-plugin-b50-analysis)](https://pypi.org/project/nonebot-plugin-b50-analysis/)
[![NoneBot2](https://img.shields.io/badge/NoneBot2-%3E%3D2.3.0-red)](https://nonebot.dev)
[![License](https://img.shields.io/github/license/HanYaaaaaaa/nonebot-plugin-b50-analysis)](LICENSE)

</div>

舞萌DX B50 数据分析 NoneBot2 插件。从水鱼查分器拉取 B50，调用 LLM 生成锐评文本并渲染分析图。


相关项目：[HanYaaaaaaa/analyze-b50](https://github.com/HanYaaaaaaa/analyze-b50)

## 安装

```bash
nb install nonebot-plugin-b50-analysis
# 或
pip install nonebot-plugin-b50-analysis
```

**必需： assets 资源包**：

```bash
# 下载并解压到任意目录，然后在 .env 中配置 B50_ASSETS_PATH
curl -O http://t23.sjcmc.cn:34274/assets.zip
unzip assets.zip -d /path/to/assets
```

## 配置

在项目的 `.env` 或 `.env.prod` 中添加以下变量：

```dotenv
# 必填：OpenAI 兼容 API 的 base URL（末尾不带斜杠）
B50_LLM_URL=https://api.openai.com/v1

# 必填：API Key
B50_LLM_KEY=sk-xxxxxxxxxxxxxxxx

# 可选：模型名称，默认 gemini-3-flash-preview
B50_LLM_MODEL=gemini-3-flash-preview

# 必填：assets 目录路径（含字体、图标、peer_stats.zip）
B50_ASSETS_PATH=/path/to/assets
```

**推荐模型：gemini-3-flash-preview**

## 使用

| 指令 | 说明 |
|------|------|
| `分析b50` | 默认风格分析自己的 B50 |
| `分析b50 [风格/需求]` | 用指定风格或需求分析自己的 B50 |

## 示例输出

![示例输出](docs/example.jpg)

## 免责声明

- 本项目未与华立科技所运营的《舞萌DX》通讯服务器进行连接，不会对玩家账号数据造成任何影响。
- 本项目数据库中保护了用户隐私，样本数据来源于OneCatBot，游玩数据仅供模型训练，并未涉及用户隐私。
- 本项目llm提示词学习的口吻均为ai爬虫在互联网自行学习，非个人意向。
- 本项目大部分由 AI 辅助生成。

## License

MIT
