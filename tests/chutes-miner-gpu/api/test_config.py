import pytest
from unittest.mock import Mock, patch, mock_open
from pathlib import Path
from fastapi.testclient import TestClient
from fastapi import FastAPI

@pytest.fixture
def app(mock_auth):
    """Create a FastAPI app with the router for testing"""        
    # Import the router after mocking auth
    from chutes_miner_gpu.api.config.router import router
    
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    """Create a test client"""
    return TestClient(app)


@pytest.fixture(scope="function")
def mock_settings():
    """Mock settings with a test kubeconfig path"""
    with patch('chutes_miner_gpu.api.config.router.settings') as mock_settings:
        mock_settings.miner_kube_config = Path("/test/path/kubeconfig")
        yield mock_settings

@pytest.fixture(scope="module")
def mock_auth():
    with patch('chutes_common.auth.authorize') as mock_auth:
        mock_auth.return_value = lambda: None

        yield mock_auth

def test_successful_kubeconfig_read(client, mock_settings):
    """Test successful reading of kubeconfig file"""
    kubeconfig_content = """
apiVersion: v1
kind: Config
clusters:
- cluster:
    server: https://test-server.com
  name: test-cluster
"""
    
    with patch('builtins.open', mock_open(read_data=kubeconfig_content)):
        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.is_file', return_value=True):
                response = client.get("/kubeconfig")
                
                assert response.status_code == 200
                assert response.json() == {"kubeconfig": kubeconfig_content}


def test_kubeconfig_file_not_found(client, mock_settings):
    """Test when kubeconfig file doesn't exist"""
    with patch('pathlib.Path.exists', return_value=False):
        response = client.get("/kubeconfig")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


def test_kubeconfig_path_is_directory(client, mock_settings):
    """Test when kubeconfig path points to a directory instead of a file"""
    with patch('pathlib.Path.exists', return_value=True):
        with patch('pathlib.Path.is_file', return_value=False):
            response = client.get("/kubeconfig")
            
            assert response.status_code == 400
            assert "not a file" in response.json()["detail"]


def test_kubeconfig_file_permission_error(client, mock_settings):
    """Test when there's no permission to read the kubeconfig file"""
    with patch('pathlib.Path.exists', return_value=True):
        with patch('pathlib.Path.is_file', return_value=True):
            with patch('builtins.open', side_effect=PermissionError("Permission denied")):
                response = client.get("/kubeconfig")
                
                assert response.status_code == 403
                assert "Permission denied" in response.json()["detail"]


def test_kubeconfig_file_not_found_exception(client, mock_settings):
    """Test FileNotFoundError during file reading"""
    with patch('pathlib.Path.exists', return_value=True):
        with patch('pathlib.Path.is_file', return_value=True):
            with patch('builtins.open', side_effect=FileNotFoundError("File not found")):
                response = client.get("/kubeconfig")
                
                assert response.status_code == 404
                assert "not found" in response.json()["detail"]


def test_kubeconfig_generic_error(client, mock_settings):
    """Test generic exception during file reading"""
    with patch('pathlib.Path.exists', return_value=True):
        with patch('pathlib.Path.is_file', return_value=True):
            with patch('builtins.open', side_effect=Exception("Generic error")):
                response = client.get("/kubeconfig")
                
                assert response.status_code == 500
                assert "Error reading kubeconfig file" in response.json()["detail"]


def test_kubeconfig_empty_file(client, mock_settings):
    """Test reading an empty kubeconfig file"""
    with patch('builtins.open', mock_open(read_data="")):
        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.is_file', return_value=True):
                response = client.get("/kubeconfig")
                
                assert response.status_code == 200
                assert response.json() == {"kubeconfig": ""}


def test_kubeconfig_with_special_characters(client, mock_settings):
    """Test reading kubeconfig with special characters and unicode"""
    kubeconfig_content = """
apiVersion: v1
kind: Config
# Special characters: àáâãäåæçèéêë
clusters:
- cluster:
    server: https://test-server.com
  name: test-cluster-™
"""
    
    with patch('builtins.open', mock_open(read_data=kubeconfig_content)):
        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.is_file', return_value=True):
                response = client.get("/kubeconfig")
                
                assert response.status_code == 200
                assert response.json() == {"kubeconfig": kubeconfig_content}


def test_different_kubeconfig_paths(client, mock_settings):
    """Test with different kubeconfig file paths"""
    test_paths = [
        "/home/user/.kube/config",
        "/etc/kubernetes/config",
        "./local-config",
        "/tmp/test-config"
    ]
    
    for path in test_paths:
        mock_settings.miner_kube_config = Path(path)
        kubeconfig_content = f"# Config for {path}"
        
        with patch('builtins.open', mock_open(read_data=kubeconfig_content)):
            with patch('pathlib.Path.exists', return_value=True):
                with patch('pathlib.Path.is_file', return_value=True):
                    response = client.get("/kubeconfig")
                    
                    assert response.status_code == 200
                    assert response.json() == {"kubeconfig": kubeconfig_content}


def test_authorization_dependency_called(client, mock_settings, mock_auth):
    """Test that the authorization dependency is properly called"""
        
    with patch('builtins.open', mock_open(read_data="test")):
        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.is_file', return_value=True):
                response = client.get("/kubeconfig")
                
                # Verify authorize was called with correct parameters
                mock_auth.assert_called_once_with(
                    allow_validator=True, 
                    purpose="management"
                )


def test_file_encoding_utf8(client, mock_settings):
    """Test that file is opened with UTF-8 encoding"""
    kubeconfig_content = "test content"
    
    with patch('builtins.open', mock_open(read_data=kubeconfig_content)) as mock_file:
        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.is_file', return_value=True):
                response = client.get("/kubeconfig")
                
                # Verify file was opened with UTF-8 encoding
                mock_file.assert_called_once_with(
                    Path(mock_settings.miner_kube_config), 
                    'r', 
                    encoding='utf-8'
                )
                assert response.status_code == 200


def test_kubeconfig_large_file(client, mock_settings):
    """Test reading a large kubeconfig file"""
    # Simulate a large kubeconfig with multiple clusters
    large_kubeconfig = """
apiVersion: v1
kind: Config
clusters:
""" + "\n".join([f"""- cluster:
    server: https://cluster-{i}.example.com
  name: cluster-{i}""" for i in range(100)])
    
    with patch('builtins.open', mock_open(read_data=large_kubeconfig)):
        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.is_file', return_value=True):
                response = client.get("/kubeconfig")
                
                assert response.status_code == 200
                assert response.json() == {"kubeconfig": large_kubeconfig}


def test_kubeconfig_with_binary_content(client, mock_settings):
    """Test handling of files with binary content that can't be decoded as UTF-8"""
    with patch('pathlib.Path.exists', return_value=True):
        with patch('pathlib.Path.is_file', return_value=True):
            with patch('builtins.open', side_effect=UnicodeDecodeError('utf-8', b'', 0, 1, 'invalid start byte')):
                response = client.get("/kubeconfig")
                
                assert response.status_code == 500
                assert "Error reading kubeconfig file" in response.json()["detail"]


def test_kubeconfig_path_construction(client, mock_settings):
    """Test that Path object is constructed correctly from settings"""
    test_path = "/custom/path/to/kubeconfig"
    mock_settings.miner_kube_config = test_path
    
    with patch('chutes_miner_gpu.api.config.router.Path') as mock_path_class:
        mock_path_instance = Mock()
        mock_path_instance.exists.return_value = True
        mock_path_instance.is_file.return_value = True
        mock_path_class.return_value = mock_path_instance
        
        with patch('builtins.open', mock_open(read_data="test content")):
            response = client.get("/kubeconfig")
            
            # Verify Path was constructed with the correct path
            mock_path_class.assert_called_once_with(test_path)
            assert response.status_code == 200