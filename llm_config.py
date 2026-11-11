"""
统一 LLM 模型名配置，避免各处硬编码。

默认使用智谱免费聊天模型 glm-4-flash-250414。
可通过环境变量 CHAT_MODEL 覆盖（例如 glm-4.5-air）。
"""
from __future__ import annotations

import os

CHAT_MODEL = os.getenv("CHAT_MODEL", "glm-4-flash-250414").strip() or "glm-4-flash-250414"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "embedding-2").strip() or "embedding-2"
