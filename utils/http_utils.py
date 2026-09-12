#!/usr/bin/env python3
"""
响应处理工具函数
"""

import json
import os
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlunparse

from curl_cffi import requests as curl_requests

if TYPE_CHECKING:
    from utils.config import AccountConfig


def resolve_account_proxy(account_config: "AccountConfig") -> dict | None:
    """解析账号代理配置（默认不启用）

    规则:
    - proxy 未配置或为 false: 不启用代理（不会自动回退到全局 PROXY）
    - proxy 为 true: 使用全局 PROXY 配置（存储在 extra["global_proxy"] 中）
    - proxy 为 dict（如 {"server": "socks5://host:port"}）: 使用自定义代理

    Args:
        account_config: 账号配置

    Returns:
        代理配置字典（Camoufox/Playwright 格式），未启用时返回 None
    """
    proxy = getattr(account_config, "proxy", None)
    if proxy is True:
        return account_config.get("global_proxy")
    if isinstance(proxy, dict) and proxy:
        return proxy
    return None


def proxy_resolve(proxy_config: dict | None = None) -> str | None:
    """将 proxy_config 转换为代理 URL 字符串

    Args:
        proxy_config: 代理配置字典

    Returns:
        代理 URL 字符串，如果没有配置代理则返回 None
    """
    if not proxy_config:
        return None

    proxy_url = proxy_config.get("server")
    if not proxy_url:
        return None

    username = proxy_config.get("username")
    password = proxy_config.get("password")

    if username and password:
        # 解析 URL 并添加认证信息
        parsed = urlparse(proxy_url)
        # 构建带认证的 URL
        netloc = f"{username}:{password}@{parsed.hostname}"
        if parsed.port:
            netloc += f":{parsed.port}"
        return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))

    return proxy_url


def response_resolve(
    response: curl_requests.Response,
    context: str,
    account_name: str,
) -> dict | None:
    """检查响应类型，如果是 HTML 则保存为文件，否则返回 JSON 数据

    Args:
        response: curl_cffi Response 对象
        context: 上下文描述，用于生成文件名
        account_name: 账号名称（用于日志和文件名）

    Returns:
        JSON 数据字典，如果响应是 HTML 则返回 None
    """
    safe_account_name = "".join(c if c.isalnum() else "_" for c in account_name)

    logs_dir = "logs"
    os.makedirs(logs_dir, exist_ok=True)

    try:
        return response.json()
    except json.JSONDecodeError as e:
        print(f"❌ {account_name}: JSON 响应解析失败: {e}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_context = "".join(c if c.isalnum() else "_" for c in context)

        content_type = response.headers.get("content-type", "").lower()

        if "text/html" in content_type or "text/plain" in content_type:
            filename = f"{safe_account_name}_{timestamp}_{safe_context}.html"
            filepath = os.path.join(logs_dir, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(response.text)

            print(f"⚠️ {account_name}: 收到 HTML 响应，已保存到: {filepath}")
        else:
            filename = f"{safe_account_name}_{timestamp}_{safe_context}_invalid.txt"
            filepath = os.path.join(logs_dir, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(response.text)

            print(f"⚠️ {account_name}: 无效响应已保存到: {filepath}")
        return None
    except Exception as e:
        print(f"❌ {account_name}: 检查和处理响应时发生错误: {e}")
        return None