#!/usr/bin/env python3
"""
Wait-for-secrets implementation for GitHub Actions
Based on https://github.com/step-security/wait-for-secrets
"""

import os
import time
from typing import Optional

from curl_cffi import requests as curl_requests


class WaitForSecrets:

    def get_oidc_token(self) -> Optional[str]:
        """Get OIDC token from GitHub Actions environment

        Returns:
                OIDC token string or None if not in GitHub Actions environment
        """
        request_token = os.getenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
        request_url = os.getenv("ACTIONS_ID_TOKEN_REQUEST_URL")

        if not request_token or not request_url:
            print("⚠️ 未在 GitHub Actions 环境中运行（OIDC token 不可用）")
            return None

        try:
            # Request OIDC token from GitHub Actions
            headers = {
                "Authorization": f"Bearer {request_token}",
                "Accept": "application/json; api-version=2.0",
                "Content-Type": "application/json",
            }

            audience_url = f"{request_url}&audience=api://ActionsOIDCGateway/Certify"
            response = curl_requests.get(audience_url, headers=headers, timeout=30)

            if response.status_code == 200:
                data = response.json()
                token = data.get("value")
                if token:
                    return token
                print("❌ 响应中未找到 OIDC token")
                return None
            print(f"❌ 获取 OIDC token 失败: HTTP {response.status_code}")
            return None

        except Exception as e:
            print(f"❌ 获取 OIDC token 时出错: {e}")
            return None

    def parse_data_from_environment(self) -> Optional[list[str]]:
        """Parse repository data from GitHub Actions environment variables

        Returns:
                List containing [owner, repo, run_id] or None if environment variables not set
        """
        repository = os.getenv("GITHUB_REPOSITORY")
        run_id = os.getenv("GITHUB_RUN_ID")

        if not repository or not run_id:
            print("⚠️ 未在 GitHub Actions 环境中运行")
            return None

        if "/" in repository:
            owner, repo = repository.split("/", 1)
        else:
            owner, repo = "", ""

        info_array = [owner, repo, run_id]
        return info_array

    def generate_secret_url(self, owner: str, repo: str, run_id: str) -> str:
        """Generate StepSecurity secret URL

        Args:
                owner: Repository owner
                repo: Repository name
                run_id: GitHub Actions run ID

        Returns:
                URL where user can input secrets
        """
        secret_url = f"https://app.stepsecurity.io/secrets/{owner}/{repo}/{run_id}"
        return secret_url

    def get(self, secrets_metadata: dict, timeout: int = 5, notification: dict = {}) -> Optional[dict]:
        """Register, poll and clear secrets from StepSecurity API

        Args:
                token: OIDC token from GitHub Actions
                secrets_metadata: Dictionary of secrets with format {name: {name: str, description: str}}
                timeout: Maximum time to wait in minutes (default: 5)

        Returns:
                Secret values or None if timeout/error
        """
        try:
            # Parse environment data
            environment_data = self.parse_data_from_environment()
            if not environment_data:
                return None

            owner, repo, run_id = environment_data[0], environment_data[1], environment_data[2]

            # Generate secret URL
            secret_url = self.generate_secret_url(owner, repo, run_id)

            # Get OIDC token
            token = self.get_oidc_token()
            if not token:
                return None

            # Use the correct API endpoint as per reference implementation
            api_url = "https://prod.api.stepsecurity.io/v1/secrets"
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

            # Convert secrets_metadata to expected payload format
            secrets_metadata_payload = []
            for secret_name, secret_info in secrets_metadata.items():
                secrets_metadata_payload.append(f"{secret_name}:")
                secrets_metadata_payload.append(f"name: {secret_info.get('name', secret_name)}")
                secrets_metadata_payload.append(f"description: {secret_info.get('description', '')}")

            # Step 1: Send PUT request to register secrets
            put_response = curl_requests.put(api_url, headers=headers, json=secrets_metadata_payload, timeout=30)

            if put_response.status_code != 200:
                print(f"❌ 注册密钥请求失败: HTTP {put_response.status_code}, {put_response.text}")
                return None

            print("✅ 密钥请求已注册")

            # Send notification with secret URL
            try:
                from utils.notify import notify

                notify_title = notification.get("title", "需要输入密钥：")
                notify_content = notification.get("content", "")
                if notify_content:
                    notify_content += "\n"
                notify_content += f"🔗 请在 {timeout} 分钟内访问以下链接输入密钥：\n{secret_url}"
                notify.push_message(notify_title, notify_content, msg_type="text")
                print("✅ 已发送带密钥链接的通知")
            except Exception as e:
                print(f"⚠️ 发送通知失败: {e}")

            # Step 2: Poll for secrets
            start_time = time.time()
            timeout_in_seconds = timeout * 60  # Convert minutes to seconds
            secrets_data = None

            print(f"⏳ 正在等待密钥（超时: {timeout} 分钟）...")
            print(f"  🔗 请访问以下链接输入密钥: {secret_url}")

            while True:
                elapsed = time.time() - start_time

                if elapsed >= timeout_in_seconds:
                    print(f"⏱️ 等待密钥超时（{timeout} 分钟）")
                    print(f"🔗 密钥链接: {secret_url}")
                    break

                try:
                    # Get OIDC token
                    token = self.get_oidc_token()
                    if not token:
                        break

                    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

                    get_response = curl_requests.get(api_url, headers=headers, timeout=30)

                    if get_response.status_code == 200:
                        data = get_response.json()
                        # Check if secrets are set (as per reference implementation)
                        are_secrets_set = data.get("areSecretsSet", False)

                        if are_secrets_set:
                            secrets_array = data.get("secrets", [])
                            if secrets_array:
                                # Convert array format to key-value object
                                # From: [{"Name":"OTP","Value":"123456",...}]
                                # To: {"OTP": "123456"}
                                secrets_data = {}
                                for secret in secrets_array:
                                    name = secret.get("Name")
                                    value = secret.get("Value")
                                    if name and value:
                                        secrets_data[name] = value
                                print(f"✅ 已收到密钥: {secrets_data}")
                                break
                        else:
                            print(f"  🔗 请访问以下链接输入密钥: {secret_url}")
                            # Wait before next polling
                            time.sleep(9)
                    else:
                        # Check response body for specific error messages
                        try:
                            body = get_response.text
                            if body != "Token used before issued":
                                print(f"响应内容: {body}")
                                break
                            # If "Token used before issued", continue polling
                        except Exception:
                            print(f"⚠️ 异常响应: HTTP {get_response.status_code}")

                except Exception as e:
                    print(f"⚠️ 轮询出错: {e}")

                # Wait before next poll
                time.sleep(1)

            # Step 3: Clear secrets from datastore
            try:
                # Get OIDC token
                token = self.get_oidc_token()
                if not token:
                    raise Exception("获取用于清除密钥的 OIDC token 失败")

                headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

                delete_response = curl_requests.delete(api_url, headers=headers, timeout=30)

                if delete_response.status_code == 200:
                    print("✅ 密钥已从数据存储中清除")
                else:
                    print(f"⚠️ 清除密钥失败: HTTP {delete_response.status_code}, {delete_response.text}")

            except Exception as e:
                print(f"⚠️ 清除密钥时出错: {e}")

            return secrets_data

        except Exception as e:
            print(f"❌ wait_for_secrets 执行出错: {e}")
            return None
