"""The CI secret scan: finds real-looking secrets, ignores placeholders, never prints the secret."""
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("scan_secrets", ROOT / "scripts" / "scan_secrets.py")
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)

# Built at run time so this file itself holds no literal that looks like a secret.
TG_TOKEN = "123456789" + ":" + "A" * 35
GH_TOKEN = "ghp_" + "a1B2" * 9
PEM = "-----BEGIN " + "RSA PRIVATE KEY-----"


def rules(text):
    return {name for _, name in scan.scan_text(text)}


def test_finds_each_kind():
    assert rules(f"TOKEN={TG_TOKEN}") == {"Telegram bot token"}
    assert rules(f"x = '{GH_TOKEN}'") == {"GitHub token"}
    assert rules(PEM) == {"private key block"}
    assert rules("AWS=AKIA" + "ABCDEFGHIJKLMNOP") == {"AWS access key id"}
    assert rules("DB=postgresql://shop:hunter2hunter2@db.example.com/shop") == {"password in a URL"}


def test_placeholders_are_fine():
    assert not rules("TOKEN=123456789:ABC-your-token-here")
    assert not rules("TOKEN=1:test")
    assert not rules("DB=postgresql://shop:${POSTGRES_PASSWORD}@db/shop")
    assert not rules("DB=postgresql://user:password@localhost/db")
    assert not rules("see https://example.com/path:with-colon@later")


def test_ignore_marker_skips_the_line():
    assert not rules(f"TOKEN={TG_TOKEN}  # secret-scan: ignore")


def test_reports_line_number_not_the_secret(tmp_path, capsys):
    f = tmp_path / "leak.env"
    f.write_text(f"A=1\nTOKEN={TG_TOKEN}\n")
    assert scan.main([str(f)]) == 1
    out = capsys.readouterr().out
    assert "leak.env:2: possible Telegram bot token" in out and TG_TOKEN not in out


def test_clean_file_passes(tmp_path, capsys):
    f = tmp_path / "ok.txt"
    f.write_text("nothing to see\n")
    assert scan.main([str(f)]) == 0


def test_binary_and_missing_files_are_skipped(tmp_path):
    b = tmp_path / "x.dat"
    b.write_bytes(b"\xff\xfe\x00")
    assert scan.scan_file(str(b)) == []
    assert scan.scan_file(str(tmp_path / "nope")) == []


def test_the_repository_itself_is_clean():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "scan_secrets.py")], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout
