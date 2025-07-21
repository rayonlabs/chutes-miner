import json
import asyncio
from unittest.mock import patch, MagicMock
from chutes_miner_cli.cli import purge_deployments, purge_deployment
from constants import CHUTE_NAME, DEPLOYMENT_ID, GPU_COUNT, SERVER_ID, SERVER_NAME


def test_purge_deployments(
    mock_hotkey_content,
    mock_client_session,
    mock_purge_deployments_response,
    tmp_path,
    monkeypatch,
    capsys,
):
    """Test purge_deployments function."""
    # Create a temporary hotkey file
    hotkey_file = tmp_path / "hotkey.json"
    hotkey_file.write_text(mock_hotkey_content)

    # Mock asyncio.run to capture the inner coroutine
    original_run = asyncio.run

    def mock_run(coro):
        return original_run(coro)

    monkeypatch.setattr(asyncio, "run", mock_run)
    _session = mock_client_session(mock_purge_deployments_response)
    monkeypatch.setattr("aiohttp.ClientSession", MagicMock(return_value=_session))

    # Run the command
    with patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock()
        mock_open.return_value.read = MagicMock(return_value=mock_hotkey_content)

        purge_deployments(hotkey=str(hotkey_file), miner_api="http://test-miner-api:32000")

    # Check that the DELETE request was made to the correct endpoint
    _session.delete.assert_called_once()
    call_args = _session.delete.call_args[0][0]
    assert call_args == "http://test-miner-api:32000/deployments/purge"

    # Check the output
    captured = capsys.readouterr()
    output_json = json.loads(captured.out)
    assert output_json["status"] == "initiated"
    assert len(output_json["deployments_purged"]) == 1
    assert output_json["deployments_purged"][0]["chute_name"] == CHUTE_NAME
    assert output_json["deployments_purged"][0]["gpu_count"] == GPU_COUNT


def test_purge_deployments_cli_integration(monkeypatch):
    """Test that the CLI command is properly registered and calls the function."""
    from chutes_miner_cli.cli import app
    from typer.testing import CliRunner

    runner = CliRunner()

    # Mock the asyncio.run to prevent actual execution
    mock_run = MagicMock()
    monkeypatch.setattr(asyncio, "run", mock_run)

    # Run the CLI command
    result = runner.invoke(app, ["purge-deployments", "--hotkey", "/path/to/hotkey.json"])

    # Check the command executed successfully
    assert result.exit_code == 0

    # Verify asyncio.run was called
    mock_run.assert_called_once()


def test_purge_deployment_by_id(
    mock_hotkey_content,
    mock_client_session,
    mock_purge_deployment_response,
    tmp_path,
    monkeypatch,
    capsys,
):
    """Test purge_deployments function."""
    # Create a temporary hotkey file
    hotkey_file = tmp_path / "hotkey.json"
    hotkey_file.write_text(mock_hotkey_content)

    # Mock asyncio.run to capture the inner coroutine
    original_run = asyncio.run

    def mock_run(coro):
        return original_run(coro)

    monkeypatch.setattr(asyncio, "run", mock_run)
    _session = mock_client_session(mock_purge_deployment_response)
    monkeypatch.setattr("aiohttp.ClientSession", MagicMock(return_value=_session))

    # Run the command
    with patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock()
        mock_open.return_value.read = MagicMock(return_value=mock_hotkey_content)

        purge_deployment(
            deployment_id="1234",
            node_id=None,
            hotkey=str(hotkey_file),
            miner_api="http://test-miner-api:32000",
        )

    # Check that the DELETE request was made to the correct endpoint
    _session.delete.assert_called_once()
    call_args = _session.delete.call_args[0][0]
    assert call_args == f"http://test-miner-api:32000/deployments/{DEPLOYMENT_ID}"

    # Check the output
    captured = capsys.readouterr()
    output_json = json.loads(captured.out)
    assert output_json["status"] == "initiated"
    assert output_json["deployment_purged"]["chute_name"] == CHUTE_NAME
    assert output_json["deployment_purged"]["gpu_count"] == GPU_COUNT


def test_purge_deployment_by_node(
    mock_hotkey_content,
    mock_client_session,
    mock_purge_deployment_response,
    tmp_path,
    monkeypatch,
    capsys,
):
    """Test purge_deployments function."""
    # Create a temporary hotkey file
    hotkey_file = tmp_path / "hotkey.json"
    hotkey_file.write_text(mock_hotkey_content)

    # Mock asyncio.run to capture the inner coroutine
    original_run = asyncio.run

    def mock_run(coro):
        return original_run(coro)

    monkeypatch.setattr(asyncio, "run", mock_run)
    _session = mock_client_session(mock_purge_deployment_response)
    monkeypatch.setattr("aiohttp.ClientSession", MagicMock(return_value=_session))

    # Run the command
    with patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock()
        mock_open.return_value.read = MagicMock(return_value=mock_hotkey_content)

        purge_deployment(
            deployment_id=None,
            node_id=SERVER_ID,
            hotkey=str(hotkey_file),
            miner_api="http://test-miner-api:32000",
        )

    # Check that the DELETE request was made to the correct endpoint
    _session.delete.assert_called_once()
    call_args = _session.delete.call_args[0][0]
    assert call_args == f"http://test-miner-api:32000/servers/{SERVER_ID}/deployments"

    # Check the output
    captured = capsys.readouterr()
    output_json = json.loads(captured.out)
    assert output_json["status"] == "initiated"
    assert output_json["deployment_purged"]["chute_name"] == CHUTE_NAME
    assert output_json["deployment_purged"]["gpu_count"] == GPU_COUNT


def test_purge_deployment_by_node_name(
    mock_hotkey_content,
    mock_client_session,
    mock_purge_deployment_response,
    tmp_path,
    monkeypatch,
    capsys,
):
    """Test purge_deployments function."""
    # Create a temporary hotkey file
    hotkey_file = tmp_path / "hotkey.json"
    hotkey_file.write_text(mock_hotkey_content)

    # Mock asyncio.run to capture the inner coroutine
    original_run = asyncio.run

    def mock_run(coro):
        return original_run(coro)

    monkeypatch.setattr(asyncio, "run", mock_run)
    _session = mock_client_session(mock_purge_deployment_response)
    monkeypatch.setattr("aiohttp.ClientSession", MagicMock(return_value=_session))

    # Run the command
    with patch("builtins.open", create=True) as mock_open:
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock()
        mock_open.return_value.read = MagicMock(return_value=mock_hotkey_content)

        purge_deployment(
            deployment_id=None,
            node_id=SERVER_NAME,
            hotkey=str(hotkey_file),
            miner_api="http://test-miner-api:32000",
        )

    # Check that the DELETE request was made to the correct endpoint
    _session.delete.assert_called_once()
    call_args = _session.delete.call_args[0][0]
    assert call_args == f"http://test-miner-api:32000/servers/{SERVER_NAME}/deployments"

    # Check the output
    captured = capsys.readouterr()
    output_json = json.loads(captured.out)
    assert output_json["status"] == "initiated"
    assert output_json["deployment_purged"]["chute_name"] == CHUTE_NAME
    assert output_json["deployment_purged"]["gpu_count"] == GPU_COUNT


def test_purge_deployment_cli_integration(monkeypatch):
    """Test that the CLI command is properly registered and calls the function."""
    from chutes_miner_cli.cli import app
    from typer.testing import CliRunner

    runner = CliRunner()

    # Mock the asyncio.run to prevent actual execution
    mock_run = MagicMock()
    monkeypatch.setattr(asyncio, "run", mock_run)

    # Run the CLI command
    result = runner.invoke(
        app,
        ["purge-deployment", "-d", DEPLOYMENT_ID, "--hotkey", "/path/to/hotkey.json"],
    )

    # Check the command executed successfully
    assert result.exit_code == 0

    # Verify asyncio.run was called
    mock_run.assert_called_once()
