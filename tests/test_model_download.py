"""Exercise Requests' real streaming decompression, not a mock of iter_content."""
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from app import model_cache, audio_preparation

MODEL = b'RNNoise test model\n' * 20000
DIGEST = hashlib.sha256(MODEL).hexdigest()

class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                body = gzip.compress(MODEL if self.path != '/wrong' else b'wrong model')
                self.send_response(200)
                self.send_header('Content-Encoding', 'gzip')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body[:-10] if self.path == '/truncated' else body)
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(3)

    def test_compressed_content_length_is_not_the_decoded_model_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'model.rnnn'
            messages = []
            model_cache.download(self.base + '/valid', target, 'RNNoise', messages.append, DIGEST)
            self.assertTrue(messages[-1].endswith('100%'))
            self.assertTrue(all(0 <= int(m.rsplit(' ', 1)[1][:-1]) <= 100 for m in messages))
            self.assertEqual(target.read_bytes(), MODEL)
            self.assertFalse(target.with_suffix('.rnnn.download').exists())

    def test_truncated_compressed_body_never_replaces_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'model.rnnn'; target.write_bytes(b'previous model')
            with self.assertRaises(Exception):
                model_cache.download(self.base + '/truncated', target, 'RNNoise', lambda _: None, DIGEST)
            self.assertEqual(target.read_bytes(), b'previous model')
            self.assertFalse(target.with_suffix('.rnnn.download').exists())

    def test_correct_http_length_does_not_bypass_the_model_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'model.rnnn'
            with self.assertRaisesRegex(RuntimeError, 'not the expected file'):
                model_cache.download(self.base + '/wrong', target, 'RNNoise', lambda _: None, DIGEST)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_suffix('.rnnn.download').exists())

    def test_corrupt_rnnoise_cache_is_repaired_and_valid_cache_is_reused_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); target = directory / audio_preparation.RNNOISE_MODEL
            target.write_bytes(b'corrupt cached model')
            def download(url, destination, name, progress, sha256):
                self.assertEqual(sha256, DIGEST); destination.write_bytes(MODEL)
            with patch.object(audio_preparation, 'RNNOISE_SHA256', DIGEST), patch.object(model_cache, 'download', side_effect=download) as request:
                self.assertEqual(audio_preparation.rnnoise_model(directory, lambda _: None), target)
                self.assertEqual(audio_preparation.rnnoise_model(directory, lambda _: None), target)
                self.assertEqual(request.call_count, 1)
