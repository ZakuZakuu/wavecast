from __future__ import annotations

from pathlib import Path

from wavecast.deployment import audio_root_from_env, normalize_database_url, resolve_audio_root


def test_normalize_hosted_postgres_urls() -> None:
    assert normalize_database_url("postgres://user:pass@host/db") == "postgresql+asyncpg://user:pass@host/db"
    assert normalize_database_url("postgresql://user:pass@host/db") == "postgresql+asyncpg://user:pass@host/db"
    explicit = "postgresql+asyncpg://user:pass@host/db"
    assert normalize_database_url(explicit) == explicit
    assert normalize_database_url("sqlite+aiosqlite:///tmp/test.db") == "sqlite+aiosqlite:///tmp/test.db"


def test_audio_root_precedence(monkeypatch) -> None:
    assert resolve_audio_root("/explicit/audio", "/railway/volume") == "/explicit/audio"
    assert resolve_audio_root(None, "/railway/volume") == "/railway/volume"
    assert resolve_audio_root(None, None) == ".wavecast-data/audio"
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", "/railway/env-volume")
    monkeypatch.delenv("WAVECAST_AUDIO_ROOT", raising=False)
    assert audio_root_from_env() == "/railway/env-volume"
    monkeypatch.setenv("WAVECAST_AUDIO_ROOT", "/explicit/env-audio")
    assert audio_root_from_env() == "/explicit/env-audio"


def test_railway_port_and_vercel_rewrite_contracts() -> None:
    entrypoint = Path("docker-entrypoint.api.sh").read_text(encoding="utf-8")
    runbook = Path("docs/deployment/railway-vercel.md").read_text(encoding="utf-8")
    next_config = Path("apps/web/next.config.ts").read_text(encoding="utf-8")
    assert "PORT:-8000" in entrypoint
    assert "WAVECAST_INTERNAL_API_URL=https://<Railway API public domain>" in runbook
    assert "process.env.WAVECAST_INTERNAL_API_URL" in next_config
    assert 'source: "/api/:path*"' in next_config
