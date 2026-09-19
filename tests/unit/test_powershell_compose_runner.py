"""Execute the wrapper with a fake Docker command; never touch running containers."""

import json
import os
import shutil
import subprocess
import sys

import pytest

POWERSHELLS = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@pytest.fixture(params=POWERSHELLS or [None])
def runner(request, tmp_path):
    if request.param is None:
        pytest.skip("PowerShell is not installed")
    root = tmp_path / "repo with spaces [literal]"
    (root / "scripts").mkdir(parents=True)
    (root / "config").mkdir()
    shutil.copyfile("run_compose.ps1", root / "run_compose.ps1")
    shutil.copyfile("scripts/read-compose-port.py", root / "scripts" / "read-compose-port.py")
    default_config = root / "config" / "application.toml"
    default_config.write_text("[server]\nport = 9123\n", encoding="utf-8")

    def run(action="start", *, config=None, docker_exit=0):
        result_file = tmp_path / "docker.json"
        state_file = tmp_path / "state.json"
        harness = tmp_path / "invoke.ps1"
        harness.write_text(
            f"""
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:APP_PORT = 'original-port'
$env:HOST_CONFIG_FILE = 'original-config'
function global:docker {{
    @{{ arguments=@($args); port=$env:APP_PORT; config=$env:HOST_CONFIG_FILE;
       cwd=(Get-Location).Path }} | ConvertTo-Json |
    Set-Content -Encoding UTF8 {ps_quote(result_file)}
    $global:LASTEXITCODE = {docker_exit}
}}
& {ps_quote(root / "run_compose.ps1")} {ps_quote(action)}
$result = $LASTEXITCODE
@{{ port=$env:APP_PORT; config=$env:HOST_CONFIG_FILE; cwd=(Get-Location).Path }} |
    ConvertTo-Json | Set-Content -Encoding UTF8 {ps_quote(state_file)}
exit $result
""",
            encoding="utf-8-sig",
        )
        env = os.environ.copy()
        env.pop("APP_CONFIG_FILE", None)
        env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env.get("PATH", "")
        if config is not None:
            env["APP_CONFIG_FILE"] = str(config)
        result = subprocess.run(
            [
                request.param,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(harness),
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        call = (
            json.loads(result_file.read_text(encoding="utf-8-sig"))
            if result_file.exists()
            else None
        )
        state = json.loads(state_file.read_text(encoding="utf-8-sig"))
        assert state == {"port": "original-port", "config": "original-config", "cwd": str(tmp_path)}
        return result, call

    return run, root, default_config


def test_start_reads_default_config_and_runs_from_script_directory(runner):
    run, root, config = runner
    result, call = run()
    assert result.returncode == 0, result.stderr
    assert call == {
        "arguments": ["compose", "-f", "compose.yaml", "up", "--build", "--detach"],
        "port": "9123",
        "config": str(config),
        "cwd": str(root),
    }


def test_custom_relative_config_with_spaces_and_unicode(runner):
    run, root, _ = runner
    custom = root.parent / "외부 설정 [test].toml"
    custom.write_text("[server]\nport = 9234\n", encoding="utf-8")
    result, call = run(config=custom.name)
    assert result.returncode == 0, result.stderr
    assert call["port"] == "9234" and call["config"] == str(custom)


@pytest.mark.parametrize("contents", [None, "[server\n", "[server]\nport = true\n"])
def test_start_rejects_invalid_config_before_docker(runner, contents):
    run, _, config = runner
    if contents is None:
        config.unlink()
    else:
        config.write_text(contents, encoding="utf-8")
    result, call = run()
    assert result.returncode == 2
    assert "compose_config_error:" in result.stderr
    assert call is None


@pytest.mark.parametrize("contents", [None, "invalid toml"])
def test_stop_works_without_valid_config(runner, contents):
    run, _, config = runner
    if contents is None:
        config.unlink()
    else:
        config.write_text(contents, encoding="utf-8")
    result, call = run("stop")
    assert result.returncode == 0, result.stderr
    assert call["arguments"] == ["compose", "-f", "compose.yaml", "down"]
    assert call["port"] == "8000"


@pytest.mark.parametrize("action", ["start", "stop"])
def test_docker_exit_code_is_preserved(runner, action):
    run, _, _ = runner
    result, call = run(action, docker_exit=17)
    assert call is not None and result.returncode == 17


@pytest.mark.parametrize("action", ["", "restart", "START"])
def test_invalid_action_prints_usage_without_docker(runner, action):
    run, _, _ = runner
    result, call = run(action)
    assert result.returncode == 2 and "Usage:" in result.stderr
    assert call is None
