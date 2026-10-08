import os
import subprocess


def test_no_tts_live_start_uses_local_database_without_minimax_credentials(tmp_path):
    fake_bin = tmp_path / 'bin'
    fake_bin.mkdir()
    for name, body in {
        'service': 'exit 0',
        'runuser': 'echo 1',
        'uv': 'if [ "$2" = "uvicorn" ]; then printf "%s\\n%s\\n" "$WAVECAST_DATABASE_URL" "$WAVECAST_TTS_PROVIDER"; fi',
    }.items():
        script = fake_bin / name
        script.write_text('#!/bin/sh\n' + body + '\n')
        script.chmod(0o755)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('MINIMAX_', 'QQ_MUSIC_'))}
    env.update({
        'PATH': str(fake_bin) + ':' + os.environ['PATH'],
        'HOME': str(tmp_path),
        'DEEPSEEK_API_KEY': 'fake', 'EXA_API_KEY': 'fake', 'TAVILY_API_KEY': 'fake',
        'NETEASE_MUSIC_API_BASE_URL': 'http://127.0.0.1:3101',
        'WAVECAST_DATABASE_URL': 'postgresql://never-use-production.invalid/db',
    })
    result = subprocess.run(['bash', 'scripts/cloud/start-api.sh', '--live', '--no-tts'],
                            env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert '127.0.0.1:5432/wavecast_cloud' in result.stdout
    assert 'never-use-production' not in result.stdout
    assert result.stdout.endswith('mock\n')
