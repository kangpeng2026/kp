#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


BASE_URL = "https://open.feishu.cn/open-apis"


def load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def request_json(method: str, path: str, *, token=None, body=None, query=None):
    url = BASE_URL + path
    if query:
        url += "?" + urllib.parse.urlencode(query)

    data = None
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}\n{payload}") from exc


def require_success(payload, step: str):
    if payload.get("code") not in (0, None):
        raise RuntimeError(f"{step} failed:\n{json.dumps(payload, ensure_ascii=False, indent=2)}")
    return payload.get("data", {})


def main() -> int:
    load_dotenv()
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")

    if not app_id or not app_secret:
        print("Missing FEISHU_APP_ID or FEISHU_APP_SECRET.")
        print("Create .env from .env.example, or set both variables in the same terminal before running.")
        return 2

    token_payload = request_json(
        "POST",
        "/auth/v3/tenant_access_token/internal",
        body={"app_id": app_id, "app_secret": app_secret},
    )
    require_success(token_payload, "get tenant_access_token")
    token = token_payload.get("tenant_access_token")
    if not token:
        raise RuntimeError(
            "get tenant_access_token did not return a token:\n"
            + json.dumps(token_payload, ensure_ascii=False, indent=2)
        )
    print("tenant_access_token: OK")

    root_payload = request_json("GET", "/drive/explorer/v2/root_folder/meta", token=token)
    root_data = require_success(root_payload, "get root folder meta")
    root_token = root_data.get("token") or root_data.get("folder_token")
    print(f"root folder token: {root_token}")

    files_payload = request_json(
        "GET",
        "/drive/v1/files",
        token=token,
        query={"folder_token": root_token, "page_size": 20},
    )
    files_data = require_success(files_payload, "list root folder files")
    files = files_data.get("files") or files_data.get("items") or []
    print(f"root folder files: {len(files)} item(s)")
    for item in files[:20]:
        name = item.get("name") or item.get("title") or "(no name)"
        typ = item.get("type") or item.get("obj_type") or "(unknown)"
        tok = item.get("token") or item.get("file_token") or item.get("obj_token") or ""
        print(f"- {name} [{typ}] {tok}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
