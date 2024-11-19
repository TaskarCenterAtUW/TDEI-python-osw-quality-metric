import unittest
from unittest.mock import MagicMock, patch
from src.services.storage_service import StorageService

class TestStorageService(unittest.TestCase):

    @patch('src.services.storage_service.Config')
    @patch('src.services.storage_service.Core')
    def setUp(self, mock_core, mock_config):
        self.mock_core = mock_core
        self.mock_config = mock_config

        # Mocking Config values
        self.mock_config.return_value.storage_container_name = 'test-container'

        # Mocking Core and Storage Client
        self.mock_storage_client = MagicMock()
        self.mock_container = MagicMock()
        self.mock_storage_client.get_container.return_value = self.mock_container
        self.mock_core.return_value.get_storage_client.return_value = self.mock_storage_client

        # Initializing the service
        self.service = StorageService(core=self.mock_core())

    def test_upload_local_file(self):
        # Mocking file creation and upload behavior
        mock_azure_file = MagicMock()
        self.mock_container.create_file.return_value = mock_azure_file
        mock_azure_file.get_remote_url.return_value = 'https://example.com/remote-path'

        # Mocking file read
        mock_local_path = 'test_local.txt'
        mock_remote_path = 'remote/test.txt'
        file_data = b'file content'

        with patch('builtins.open', unittest.mock.mock_open(read_data=file_data)) as mock_file:
            remote_url = self.service.upload_local_file(mock_local_path, mock_remote_path)

        # Assertions
        self.mock_container.create_file.assert_called_once_with(mock_remote_path)
        mock_azure_file.upload.assert_called_once_with(file_data)
        mock_file.assert_called_once_with(mock_local_path, 'rb')
        self.assertEqual(remote_url, 'https://example.com/remote-path')

    def test_download_remote_file(self):
        # Mocking file entity and stream
        mock_file_entity = MagicMock()
        mock_file_entity.get_stream.return_value = b'file content'
        self.mock_storage_client.get_file_from_url.return_value = mock_file_entity

        # Mocking file write
        mock_remote_path = 'remote/test.txt'
        mock_local_path = 'test_local.txt'

        with patch('builtins.open', unittest.mock.mock_open()) as mock_file:
            self.service.download_remote_file(mock_remote_path, mock_local_path)

        # Assertions
        self.mock_storage_client.get_file_from_url.assert_called_once_with(
            self.mock_config.return_value.storage_container_name, mock_remote_path
        )
        mock_file.assert_called_once_with(mock_local_path, 'wb')
        mock_file().write.assert_called_once_with(b'file content')

if __name__ == '__main__':
    unittest.main()
