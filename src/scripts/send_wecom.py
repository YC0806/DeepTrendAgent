#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from importlib import import_module
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = PACKAGE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
PACKAGE_NAME = PACKAGE_DIR.name

models = import_module(f"{PACKAGE_NAME}.models")
provider = import_module(f"{PACKAGE_NAME}.provider")
tools = import_module(f"{PACKAGE_NAME}.tools")

Delivery = models.Delivery
utcnow_iso = models.utcnow_iso
WeComWebhookProvider = provider.WeComWebhookProvider
WECOM_DIGEST_CHAR_LIMIT = tools.WECOM_DIGEST_CHAR_LIMIT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send a DeepTrend report digest and attachment through the WeCom webhook channel."
    )
    summary_group = parser.add_mutually_exclusive_group(required=True)
    summary_group.add_argument("--summary-text", help="WeCom markdown digest content.")
    summary_group.add_argument("--summary-path", help="Path to a UTF-8 markdown digest file.")
    parser.add_argument("--attachment-path", required=True)
    parser.add_argument(
        "--attachment-filename",
        help="Optional display filename for the WeCom upload. Defaults to the attachment path basename.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _read_summary(*, summary_text: str | None, summary_path: str | None) -> str:
    if summary_text is not None:
        return summary_text
    assert summary_path is not None
    path = Path(summary_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"WeCom summary file not found: {path}")
    return path.read_text(encoding="utf-8")


def _validate(*, summary: str, attachment_path: Path) -> None:
    if not summary.strip():
        raise ValueError("WeCom summary is empty")
    if len(summary) > WECOM_DIGEST_CHAR_LIMIT:
        raise ValueError(f"WeCom summary exceeds {WECOM_DIGEST_CHAR_LIMIT} characters")
    if not attachment_path.is_file():
        raise FileNotFoundError(f"WeCom attachment file not found: {attachment_path}")


def _send(*, summary: str, attachment_path: Path, attachment_filename: str | None = None) -> Delivery:
    started = utcnow_iso()
    sender = WeComWebhookProvider()
    try:
        sender.send_markdown_v2(summary)
        media_id = sender.upload_file(attachment_path, filename=attachment_filename)
        sender.send_file(media_id)
        return Delivery(
            channel="wecom",
            status="success",
            summary="wecom: digest + attachment sent",
            sent_at=started,
        )
    except Exception as exc:
        return Delivery(
            channel="wecom",
            status="failed",
            summary=f"wecom: {exc}",
            sent_at=started,
            error=str(exc),
        )


def main() -> int:
    args = parse_args()
    try:
        summary = _read_summary(summary_text=args.summary_text, summary_path=args.summary_path)
        attachment_path = Path(args.attachment_path).expanduser().resolve()
        if args.attachment_filename is not None:
            WeComWebhookProvider.validate_upload_filename(args.attachment_filename)
        _validate(summary=summary, attachment_path=attachment_path)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.dry_run:
        delivery = Delivery(
            channel="wecom",
            status="skipped",
            summary="wecom: dry-run, no outbound request sent",
            sent_at=utcnow_iso(),
        )
    elif not (WeComWebhookProvider().webhook_key or "").strip():
        delivery = Delivery(
            channel="wecom",
            status="skipped",
            summary="wecom: WECOM_WEBHOOK_KEY not set",
            sent_at=utcnow_iso(),
        )
    else:
        delivery = _send(
            summary=summary,
            attachment_path=attachment_path,
            attachment_filename=args.attachment_filename,
        )

    print(json.dumps(delivery.to_dict(), ensure_ascii=False))
    return 0 if delivery.status != "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
