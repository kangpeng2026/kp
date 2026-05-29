#!/usr/bin/env python3
import json
import mimetypes
import os
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


BASE_URL = "https://open.feishu.cn/open-apis"


def load_dotenv(path=".env"):
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def request_json(method, path, token=None, body=None, query=None, headers=None, data=None):
    url = BASE_URL + path
    if query:
        url += "?" + urllib.parse.urlencode(query)

    req_headers = headers.copy() if headers else {}
    if token:
        req_headers["Authorization"] = "Bearer " + token
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json; charset=utf-8")

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError("HTTP %s %s\n%s" % (exc.code, url, payload))


def require_success(payload, step):
    if payload.get("code") != 0:
        raise RuntimeError(step + " failed:\n" + json.dumps(payload, ensure_ascii=False, indent=2))
    return payload.get("data") or {}


def tenant_access_token():
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        raise RuntimeError("Missing FEISHU_APP_ID or FEISHU_APP_SECRET")

    payload = request_json(
        "POST",
        "/auth/v3/tenant_access_token/internal",
        body={"app_id": app_id, "app_secret": app_secret},
    )
    require_success(payload, "get tenant_access_token")
    token = payload.get("tenant_access_token")
    if not token:
        raise RuntimeError("tenant_access_token missing from response")
    return token


def root_folder_token(token):
    payload = request_json("GET", "/drive/explorer/v2/root_folder/meta", token=token)
    data = require_success(payload, "get root folder meta")
    folder_token = data.get("token") or data.get("folder_token")
    if not folder_token:
        raise RuntimeError("root folder token missing:\n" + json.dumps(payload, ensure_ascii=False, indent=2))
    return folder_token


def create_folder(token, parent_folder_token, name):
    payload = request_json(
        "POST",
        "/drive/v1/files/create_folder",
        token=token,
        body={"folder_token": parent_folder_token, "name": name},
    )
    data = require_success(payload, "create folder")
    folder_token = data.get("token")
    if not folder_token:
        raise RuntimeError("create folder returned no token:\n" + json.dumps(payload, ensure_ascii=False, indent=2))
    return folder_token, data.get("url")


def encode_multipart(fields, file_field, file_path):
    boundary = "----codex-feishu-%s" % uuid.uuid4().hex
    chunks = []
    for key, value in fields.items():
        chunks.append(("--%s\r\n" % boundary).encode())
        chunks.append(('Content-Disposition: form-data; name="%s"\r\n\r\n' % key).encode())
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")

    file_name = os.path.basename(file_path)
    content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    chunks.append(("--%s\r\n" % boundary).encode())
    chunks.append(
        ('Content-Disposition: form-data; name="%s"; filename="%s"\r\n' % (file_field, file_name)).encode()
    )
    chunks.append(("Content-Type: %s\r\n\r\n" % content_type).encode())
    chunks.append(Path(file_path).read_bytes())
    chunks.append(b"\r\n")
    chunks.append(("--%s--\r\n" % boundary).encode())
    body = b"".join(chunks)
    return body, "multipart/form-data; boundary=%s" % boundary


def upload_file(token, folder_token, file_path):
    file_size = os.path.getsize(file_path)
    fields = {
        "file_name": os.path.basename(file_path),
        "parent_type": "explorer",
        "parent_node": folder_token,
        "size": str(file_size),
    }
    body, content_type = encode_multipart(fields, "file", file_path)
    payload = request_json(
        "POST",
        "/drive/v1/files/upload_all",
        token=token,
        headers={"Content-Type": content_type},
        data=body,
    )
    return require_success(payload, "upload file")


def list_files(token, folder_token):
    payload = request_json(
        "GET",
        "/drive/v1/files",
        token=token,
        query={"folder_token": folder_token, "page_size": 20},
    )
    data = require_success(payload, "list files")
    return data.get("files") or data.get("items") or []


def main():
    load_dotenv()
    token = tenant_access_token()
    print("tenant_access_token: OK")

    root = root_folder_token(token)
    print("root folder token: %s" % root)

    folder_name = "Codex托管文件-%s" % time.strftime("%Y%m%d-%H%M%S")
    folder_token, folder_url = create_folder(token, root, folder_name)
    print("created folder: %s" % folder_name)
    print("folder token: %s" % folder_token)
    if folder_url:
        print("folder url: %s" % folder_url)

    sample_path = Path("feishu_upload_test.txt")
    sample_path.write_text(
        "Codex Feishu Drive smoke test\ncreated_at=%s\n" % time.strftime("%Y-%m-%d %H:%M:%S"),
        encoding="utf-8",
    )
    uploaded = upload_file(token, folder_token, str(sample_path))
    print("uploaded file: %s" % sample_path.name)
    print("upload response: %s" % json.dumps(uploaded, ensure_ascii=False))

    files = list_files(token, folder_token)
    print("folder files: %d item(s)" % len(files))
    for item in files:
        name = item.get("name") or item.get("title") or "(no name)"
        typ = item.get("type") or item.get("obj_type") or "(unknown)"
        tok = item.get("token") or item.get("file_token") or item.get("obj_token") or ""
        print("- %s [%s] %s" % (name, typ, tok))


if __name__ == "__main__":
    main()
