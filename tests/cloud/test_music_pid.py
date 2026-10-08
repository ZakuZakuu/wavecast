import os
import signal
import subprocess
import time
from pathlib import Path


def test_native_launcher_records_upstream_process_instead_of_wrapper_shell(tmp_path):
    source = Path('scripts/cloud/start-music.sh').read_text()
    end = source.index('\n  echo "Upstream log:')
    start = source.rindex('  (cd "$upstream_dir"', 0, end)
    fragment = source[start:end]
    fake_node = tmp_path / 'node'
    fake_node.write_text('#!/bin/sh\nprintf \"%s\" \"$$\" > \"$data_dir/node-actual.pid\"\nexec sleep 30\n')
    fake_node.chmod(0o755)
    env = dict(os.environ, PATH=str(tmp_path) + ':' + os.environ['PATH'],
               upstream_dir=str(tmp_path), data_dir=str(tmp_path))
    proc = subprocess.Popen(['bash', '-c', fragment], env=env, start_new_session=True)
    try:
        assert proc.wait(timeout=5) == 0
        pid = int((tmp_path / 'ncm-upstream.pid').read_text())
        actual = tmp_path / 'node-actual.pid'
        for _ in range(50):
            if actual.exists() and actual.read_text():
                break
            time.sleep(0.02)
        assert pid == int(actual.read_text())

    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
