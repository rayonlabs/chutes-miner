import pytest
from unittest.mock import patch, MagicMock
import os
from chutes_agent.config import AgentSettings, settings
from loguru import logger

def test_agent_settings_default_values():
    """Test that default values are set correctly"""
    test_settings = AgentSettings(cluster_name="test-cluster")
    
    assert test_settings.cluster_name == "test-cluster"
    assert test_settings.control_plane_timeout == 30
    assert test_settings.control_plane_retry_attempts == 3
    assert test_settings.heartbeat_interval == 30
    assert test_settings.watch_namespaces == []
    assert test_settings.log_level == "INFO"
    assert test_settings.batch_size == 100
    assert test_settings.batch_timeout == 5

def test_agent_settings_environment_override():
    """Test that environment variables override defaults"""
    with patch.dict(os.environ, {
        'CLUSTER_NAME': 'env-cluster',
        'CONTROL_PLANE_TIMEOUT': '60',
        'HEARTBEAT_INTERVAL': '45',
        'LOG_LEVEL': 'DEBUG',
        'WATCH_NAMESPACES': '["ns1", "ns2"]'
    }):
        test_settings = AgentSettings()
        assert test_settings.cluster_name == 'env-cluster'
        assert test_settings.control_plane_timeout == 60
        assert test_settings.heartbeat_interval == 45
        assert test_settings.log_level == 'DEBUG'

def test_agent_settings_field_validation():
    """Test field validation"""
    # Should work with valid values
    test_settings = AgentSettings(
        cluster_name="valid-cluster",
        control_plane_timeout=30,
        heartbeat_interval=60
    )
    assert test_settings.cluster_name == "valid-cluster"
    assert test_settings.control_plane_timeout == 30

@patch('loguru.logger.remove')
@patch('loguru.logger.add')
@patch('loguru.logger.info')
def test_setup_logging(mock_info, mock_add, mock_remove):
    """Test logging setup"""
    test_settings = AgentSettings(cluster_name="test")
    test_settings.setup_logging()
    
    mock_remove.assert_called_once()
    mock_add.assert_called_once()
    mock_info.assert_called_once()

def test_global_settings_instance():
    """Test that global settings instance exists"""
    assert settings is not None
    assert hasattr(settings, 'cluster_name')