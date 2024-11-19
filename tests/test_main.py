import unittest
import asyncio
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.main import app, startup_event, shutdown_event


class TestFastAPIApp(unittest.TestCase):
    def setUp(self):
        # Setup the TestClient for FastAPI app
        self.client = TestClient(app)

    def test_root_endpoint(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'Hello': 'World'})

    def test_ping_endpoint(self):
        response = self.client.get('/ping')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'msg': 'Ping Successful'})

    def test_health_endpoint(self):
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), "I'm healthy !!")

    @patch('src.main.ServiceBusService')
    def test_startup_event_initializes_servicebus(self, MockServiceBusService):
        mock_service = MagicMock()
        MockServiceBusService.return_value = mock_service

        asyncio.run(startup_event())

        # Check if ServiceBusService is initialized
        self.assertEqual(app.qm_service, mock_service)

    @patch.object(app, 'qm_service')
    def test_shutdown_event_calls_service_stop(self, mock_qm_service):
        mock_qm_service.stop = MagicMock()

        asyncio.run(shutdown_event())

        # Verify the stop method is called
        mock_qm_service.stop.assert_called_once()

    def test_octet_stream_response(self):
        from src.main import OctetStreamResponse

        response = OctetStreamResponse(content=b'binary data')
        self.assertEqual(response.media_type, 'application/octet-stream')
        self.assertEqual(response.body, b'binary data')


if __name__ == '__main__':
    unittest.main()
