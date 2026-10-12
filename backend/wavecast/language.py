"""Spoken-language choice for one programme, kept dependency-free so any layer can import it."""

from __future__ import annotations

from enum import StrEnum


class OutputLanguage(StrEnum):
    """Supported spoken-language choices for one assembled program."""

    AUTO = "auto"
    ZH_CN = "zh-CN"
    EN_US = "en-US"
    JA_JP = "ja-JP"
