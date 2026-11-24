from __future__ import annotations

import os
import types
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Union, get_args, get_origin


_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENV_FILE = _REPO_ROOT / ".env"
_UNION_TYPE = getattr(types, "UnionType", None)
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _unwrap_optional(field_type: Any) -> Any:
    origin = get_origin(field_type)
    if origin not in {Union, _UNION_TYPE}:
        return field_type
    args = [arg for arg in get_args(field_type) if arg is not type(None)]
    return args[0] if len(args) == 1 else field_type


def _coerce_value(raw_value: str, field_type: Any) -> Any:
    target_type = _unwrap_optional(field_type)
    if target_type is bool:
        normalized = raw_value.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
        return bool(raw_value)
    if target_type is int:
        return int(raw_value)
    if target_type is float:
        return float(raw_value)
    return raw_value


@dataclass
class Settings:
    github_token: str = ""
    github_base_url: str = "https://github.com"
    github_api_base_url: str = "https://api.github.com"
    github_trending_archive_repo_full_name: str = "antonkomarev/github-trending-archive"
    github_trending_archive_ref: str = "main"
    github_user_agent: str = ""
    github_proxy_url: str = ""
    git_bin: str = "git"
    deeptrend_git_cache_root: str = str(_REPO_ROOT / "tmp" / "git-cache")
    deeptrend_artifact_root: str = "backend/output/trend"
    wecom_webhook_key: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        env_values = _load_env_file(_ENV_FILE)
        env_values.update(os.environ)

        kwargs: dict[str, Any] = {}
        for field_info in fields(cls):
            env_name = field_info.name.upper()
            raw_value = env_values.get(env_name)
            if raw_value is None:
                continue
            kwargs[field_info.name] = _coerce_value(raw_value, field_info.type)
        return cls(**kwargs)


settings = Settings.from_env()


__all__ = [
    "Settings",
    "settings",
]
