from __future__ import annotations

import json
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from ...config import settings


class WeComWebhookProvider:
    """Enterprise WeCom webhook sender for markdown and file messages."""

    def __init__(
        self,
        *,
        webhook_key: str | None = None,
        timeout: int = 10,
        request_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        self.webhook_key = webhook_key or settings.wecom_webhook_key
        self.timeout = timeout
        self.request_retries = max(1, request_retries)
        self.retry_delay = max(0.0, retry_delay)

    def send_markdown_v2(self, content: str) -> dict[str, Any]:
        payload = {
            "msgtype": "markdown_v2",
            "markdown_v2": {
                "content": content,
            },
        }
        return self._post_json(
            self._send_url(),
            payload=payload,
            operation="WeCom markdown_v2",
        )

    def upload_file(self, path: Path, *, filename: str | None = None) -> str:
        resolved_path = path.expanduser().resolve()
        if not resolved_path.exists():
            raise FileNotFoundError(f"WeCom upload file not found: {resolved_path}")

        upload_filename = self.validate_upload_filename(filename) if filename is not None else None
        response = self._post_multipart_file(
            self._upload_url(file_type="file"),
            path=resolved_path,
            operation="WeCom upload file",
            filename=upload_filename,
        )
        media_id = str(response.get("media_id") or "").strip()
        if not media_id:
            raise RuntimeError(f"WeCom upload response missing media_id: {response}")
        return media_id

    def send_file(self, media_id: str) -> dict[str, Any]:
        payload = {
            "msgtype": "file",
            "file": {
                "media_id": media_id,
            },
        }
        return self._post_json(
            self._send_url(),
            payload=payload,
            operation="WeCom file",
        )

    def _send_url(self) -> str:
        key = self._require_webhook_key()
        return f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"

    def _upload_url(self, *, file_type: str) -> str:
        key = self._require_webhook_key()
        return f"https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={key}&type={file_type}"

    def _require_webhook_key(self) -> str:
        key = (self.webhook_key or "").strip()
        if not key:
            raise ValueError("WECOM_WEBHOOK_KEY is not set")
        return key

    def _post_json(
        self,
        url: str,
        *,
        payload: dict[str, Any],
        operation: str,
    ) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._request_with_retry(
            url=url,
            body=body,
            headers=headers,
            operation=operation,
        )

    def _post_multipart_file(
        self,
        url: str,
        *,
        path: Path,
        operation: str,
        filename: str | None = None,
    ) -> dict[str, Any]:
        boundary = f"----DeepTrend{uuid.uuid4().hex}"
        body = self._build_multipart_body(path=path, boundary=boundary, filename=filename)
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        }
        return self._request_with_retry(
            url=url,
            body=body,
            headers=headers,
            operation=operation,
        )

    def _build_multipart_body(self, *, path: Path, boundary: str, filename: str | None = None) -> bytes:
        upload_filename = self.validate_upload_filename(filename) if filename is not None else path.name
        mime_type = mimetypes.guess_type(upload_filename)[0] or "application/octet-stream"
        content = path.read_bytes()
        header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="media"; filename="{upload_filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
        footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
        return header + content + footer

    @staticmethod
    def validate_upload_filename(filename: str) -> str:
        upload_filename = filename.strip()
        if not upload_filename:
            raise ValueError("WeCom upload filename must be non-empty")
        if Path(upload_filename).name != upload_filename or "\r" in upload_filename or "\n" in upload_filename:
            raise ValueError(f"WeCom upload filename must be a plain basename: {filename!r}")
        return upload_filename

    def _request_with_retry(
        self,
        *,
        url: str,
        body: bytes,
        headers: dict[str, str],
        operation: str,
    ) -> dict[str, Any]:
        last_exc: BaseException | None = None

        for attempt in range(1, self.request_retries + 1):
            try:
                response = self._request_once(url, body, headers)
                self._raise_if_wecom_error(response=response, operation=operation)
                return response
            except Exception as exc:
                last_exc = exc
                if attempt < self.request_retries and self.retry_delay > 0:
                    time.sleep(self.retry_delay)

        assert last_exc is not None
        raise RuntimeError(f"{operation} failed after {self.request_retries} attempts") from last_exc

    def _request_once(
        self,
        url: str,
        body: bytes,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        request = Request(url, data=body, headers=headers, method="POST")
        with urlopen(request, timeout=self.timeout) as response:
            raw = response.read().decode("utf-8", errors="ignore")
        return json.loads(raw or "{}")

    def _raise_if_wecom_error(self, *, response: dict[str, Any], operation: str) -> None:
        errcode = int(response.get("errcode", 0) or 0)
        if errcode != 0:
            errmsg = str(response.get("errmsg") or "unknown error")
            raise RuntimeError(f"{operation} failed: errcode={errcode} errmsg={errmsg}")
