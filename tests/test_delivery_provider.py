from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from deeptrend.provider import WeComWebhookProvider


class WeComWebhookProviderTests(unittest.TestCase):
    def test_send_markdown_v2_posts_expected_payload(self) -> None:
        provider = WeComWebhookProvider(webhook_key="test-key", request_retries=1, retry_delay=0)
        seen: dict[str, object] = {}

        def fake_request_once(url: str, body: bytes, headers: dict[str, str]) -> dict[str, object]:
            seen["url"] = url
            seen["payload"] = json.loads(body.decode("utf-8"))
            seen["headers"] = headers
            return {"errcode": 0, "errmsg": "ok", "msgid": "mid-1"}

        provider._request_once = fake_request_once  # type: ignore[method-assign]

        response = provider.send_markdown_v2("# DeepTrend")

        self.assertEqual(response["msgid"], "mid-1")
        self.assertEqual(
            seen["url"],
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key",
        )
        self.assertEqual(
            seen["payload"],
            {
                "msgtype": "markdown_v2",
                "markdown_v2": {"content": "# DeepTrend"},
            },
        )
        self.assertEqual(seen["headers"], {"Content-Type": "application/json", "Accept": "application/json"})

    def test_upload_file_returns_media_id(self) -> None:
        provider = WeComWebhookProvider(webhook_key="test-key", request_retries=1, retry_delay=0)
        seen: dict[str, object] = {}

        def fake_post_multipart_file(
            url: str,
            *,
            path: Path,
            operation: str,
            filename: str | None = None,
        ) -> dict[str, object]:
            seen["url"] = url
            seen["path"] = str(path)
            seen["filename"] = filename
            seen["operation"] = operation
            return {"errcode": 0, "errmsg": "ok", "media_id": "media-1"}

        provider._post_multipart_file = fake_post_multipart_file  # type: ignore[method-assign]

        with tempfile.TemporaryDirectory() as tmpdir:
            attachment_path = Path(tmpdir) / "report.md"
            attachment_path.write_text("# report\n", encoding="utf-8")
            media_id = provider.upload_file(attachment_path)

        self.assertEqual(media_id, "media-1")
        self.assertEqual(
            seen["url"],
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key=test-key&type=file",
        )
        self.assertEqual(seen["operation"], "WeCom upload file")
        self.assertIsNone(seen["filename"])

    def test_upload_file_accepts_display_filename(self) -> None:
        provider = WeComWebhookProvider(webhook_key="test-key", request_retries=1, retry_delay=0)
        seen: dict[str, object] = {}

        def fake_post_multipart_file(
            url: str,
            *,
            path: Path,
            operation: str,
            filename: str | None = None,
        ) -> dict[str, object]:
            seen["path"] = str(path)
            seen["filename"] = filename
            seen["operation"] = operation
            return {"errcode": 0, "errmsg": "ok", "media_id": "media-1"}

        provider._post_multipart_file = fake_post_multipart_file  # type: ignore[method-assign]

        with tempfile.TemporaryDirectory() as tmpdir:
            attachment_path = Path(tmpdir) / "report.md"
            attachment_path.write_text("# report\n", encoding="utf-8")
            media_id = provider.upload_file(
                attachment_path,
                filename="2026-04-03__github-trending-daily-python.md",
            )

        self.assertEqual(media_id, "media-1")
        self.assertEqual(seen["filename"], "2026-04-03__github-trending-daily-python.md")
        self.assertEqual(seen["operation"], "WeCom upload file")

    def test_rejects_nested_display_filename(self) -> None:
        provider = WeComWebhookProvider(webhook_key="test-key", request_retries=1, retry_delay=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            attachment_path = Path(tmpdir) / "report.md"
            attachment_path.write_text("# report\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "plain basename"):
                provider.upload_file(attachment_path, filename="../report.md")

    def test_send_file_posts_expected_payload(self) -> None:
        provider = WeComWebhookProvider(webhook_key="test-key", request_retries=1, retry_delay=0)
        seen: dict[str, object] = {}

        def fake_request_once(url: str, body: bytes, headers: dict[str, str]) -> dict[str, object]:
            seen["url"] = url
            seen["payload"] = json.loads(body.decode("utf-8"))
            seen["headers"] = headers
            return {"errcode": 0, "errmsg": "ok"}

        provider._request_once = fake_request_once  # type: ignore[method-assign]

        response = provider.send_file("media-1")

        self.assertEqual(response["errmsg"], "ok")
        self.assertEqual(
            seen["payload"],
            {
                "msgtype": "file",
                "file": {"media_id": "media-1"},
            },
        )


if __name__ == "__main__":
    unittest.main()
