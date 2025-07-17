import pytest
import os
from unittest.mock import patch

from chutes_monitor.config import MonitorSettings


def test_monitor_settings_default_values():
    """Test MonitorSettings uses default values correctly"""
    # Clear environment variables
    env_vars = ['HEALTH_CHECK_INTERVAL', 'HEALTH_FAILURE_THRESHOLD', 'REDIS_URL']
    original_values = {}
    
    for var in env_vars:
        original_values[var] = os.environ.get(var)
        if var in os.environ:
            del os.environ[var]
    
    try:
        settings = MonitorSettings()
        
        # Note: The config has a syntax error with trailing commas, but assuming correct values
        assert settings.heartbeat_interval == 30  # Default from code
        assert settings.failure_threshold == 1    # Default from code
        assert settings.redis_url == 'redis://redis:6379'  # Default from code
    
    finally:
        # Restore original environment variables
        for var, value in original_values.items():
            if value is not None:
                os.environ[var] = value


def test_monitor_settings_custom_values():
    """Test MonitorSettings uses custom environment values"""
    custom_values = {
        'HEARTBEAT_INTERVAL': '60',
        'HEALTH_FAILURE_THRESHOLD': '3',
        'REDIS_URL': 'redis://custom-redis:6380'
    }
    
    # Store original values
    original_values = {}
    for var in custom_values:
        original_values[var] = os.environ.get(var)
    
    try:
        # Set custom values
        for var, value in custom_values.items():
            os.environ[var] = value
        
        settings = MonitorSettings()
        
        assert settings.heartbeat_interval == 60
        assert settings.failure_threshold == 3
        assert settings.redis_url == 'redis://custom-redis:6380'
    
    finally:
        # Restore original values
        for var, value in original_values.items():
            if value is not None:
                os.environ[var] = value
            elif var in os.environ:
                del os.environ[var]