"""Tests for the --hoist / --tunnel public-URL integrations.

These mock out shutil.which and subprocess so CI (which has neither
cloudflared nor hoist nor a configured Cloudflare Tunnel) can verify the
graceful-degradation paths without needing real binaries.
"""

from unittest.mock import patch

from beacon.cli import _start_hoist, _start_tunnel


def test_start_tunnel_without_cloudflared_prints_hint_and_returns_none(capsys):
    with patch("beacon.cli.shutil.which", return_value=None):
        result = _start_tunnel(8420)
    assert result is None
    assert "cloudflared not found" in capsys.readouterr().out


def test_start_hoist_without_hoist_prints_hint(capsys):
    with patch("beacon.cli.shutil.which", return_value=None):
        _start_hoist("beacon", 8420)
    assert "'hoist' not found on PATH" in capsys.readouterr().out


def test_start_hoist_calls_adopt_once_ready(capsys):
    with patch("beacon.cli.shutil.which", return_value="/usr/local/bin/hoist"), \
         patch("beacon.cli._wait_until_ready", return_value=True), \
         patch("beacon.cli.subprocess.run") as mock_run:
        _start_hoist("myrelay", 8420)
        # _start_hoist spawns a daemon thread; give it a moment to run.
        import time
        time.sleep(0.2)

    mock_run.assert_called_once_with(["hoist", "adopt", "myrelay", "--port", "8420"])


def test_start_hoist_skips_adopt_if_never_ready(capsys):
    with patch("beacon.cli.shutil.which", return_value="/usr/local/bin/hoist"), \
         patch("beacon.cli._wait_until_ready", return_value=False), \
         patch("beacon.cli.subprocess.run") as mock_run:
        _start_hoist("myrelay", 8420)
        import time
        time.sleep(0.2)

    mock_run.assert_not_called()
    assert "never became ready" in capsys.readouterr().out
