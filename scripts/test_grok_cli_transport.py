import json
import base64
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zlib
import uuid
from urllib.parse import quote

import grok_cli_transport as transport


def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00')) + chunk(b'IEND', b''))


JPEG = base64.b64decode(
    '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDi6KKK+ZP3E//Z')


class GrokTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.session_id = str(uuid.uuid4())
        self.session = self.root / quote(str(self.root), safe='') / self.session_id
        (self.session / 'images').mkdir(parents=True)
        self.source = self.session / 'images/1.png'
        self.source.write_bytes(png())
        self.events = [
            {'type': 'assistant', 'tool_calls': [{'id': 'c1', 'name': 'image_gen'}]},
            {'type': 'tool_result', 'tool_call_id': 'c1', 'content': json.dumps({'path': str(self.source)})},
        ]
        self.history()

    def history(self):
        (self.session / 'chat_history.jsonl').write_text('\n'.join(map(json.dumps, self.events)))

    def record(self):
        record = {'transport': 'grok-cli', 'session_dir': str(self.session), 'tool': 'image_gen',
                  'output_path': str(self.root / 'result.png'), 'session_id': self.session_id,
                  'run_dir': str(self.root)}
        transport.save_record(self.root, record)
        return record

    def test_native_result_delivery_and_idempotent_recovery(self):
        self.record()
        first = transport.recover(self.root)
        self.assertEqual(first['transport_state'], 'succeeded')
        self.assertEqual((self.root / 'result.png').read_bytes(), png())
        self.assertEqual(transport.recover(self.root)['output_sha256'], first['output_sha256'])

    def test_prose_is_not_evidence(self):
        self.events = [{'type': 'assistant', 'content': str(self.source)}]
        self.history()
        with self.assertRaises(transport.TransportError):
            transport.session_artifact(self.session, 'image_gen')

    def test_result_must_match_native_call(self):
        self.events[0]['tool_calls'][0]['name'] = 'shell'
        self.history()
        with self.assertRaises(transport.TransportError):
            transport.session_artifact(self.session, 'image_gen')

    def test_foreign_session_rejected(self):
        self.events[1]['content'] = json.dumps({'path': str(self.root / 'other.png')})
        self.history()
        with self.assertRaises(transport.TransportError):
            transport.session_artifact(self.session, 'image_gen')

    def test_multiple_native_calls_rejected(self):
        self.events[0]['tool_calls'].append({'id': 'c2', 'name': 'image_gen'})
        self.history()
        with self.assertRaises(transport.TransportError):
            transport.session_artifact(self.session, 'image_gen')

    def test_existing_file_never_overwritten(self):
        self.record()
        output = self.root / 'result.png'
        output.write_bytes(b'original')
        with self.assertRaises(transport.TransportError):
            transport.recover(self.root)
        self.assertEqual(output.read_bytes(), b'original')

    def test_symlink_rejected(self):
        other = self.root / 'actual.png'
        self.source.rename(other)
        self.source.symlink_to(other)
        with self.assertRaises(transport.TransportError):
            transport.session_artifact(self.session, 'image_gen')

    def test_truncated_jpeg_rejected(self):
        self.source.write_bytes(b'\xff\xd8\xff\xc0\x00\x11')
        with self.assertRaises(transport.TransportError):
            transport.inspect_image(self.source)

    def test_dry_run_does_not_launch_or_create_directories(self):
        with patch.object(transport.shutil, 'which', return_value='/bin/grok'), patch.object(transport.subprocess, 'run') as launch:
            result = transport.run('cup', self.root / 'new/cup.jpg')
        launch.assert_not_called()
        self.assertEqual(result['transport_state'], 'dry_run')
        self.assertFalse((self.root / 'new').exists())

    def test_timeout_is_unknown_and_never_retried(self):
        with patch.object(transport.shutil, 'which', return_value='/bin/grok'), patch.object(
                transport.subprocess, 'run', side_effect=subprocess.TimeoutExpired('grok', 1)) as launch:
            with self.assertRaisesRegex(transport.TransportError, 'do not regenerate'):
                transport.run('cup', self.root / 'cup.jpg', execute=True, timeout=1)
        self.assertEqual(launch.call_count, 1)
        records = list((self.root / '.grok-runs').glob('*/provenance.json'))
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0].read_text())['transport_state'], 'outcome_unknown')

    def test_nonzero_cli_exit_never_auto_delivers(self):
        def cli(command, **kwargs):
            sid = command[command.index('--session-id') + 1]
            self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
            return subprocess.CompletedProcess(command, 1, json.dumps({'sessionId': sid}), 'secret sentinel')
        with patch.object(transport.shutil, 'which', return_value='/bin/grok'), patch.object(
                transport.subprocess, 'run', side_effect=cli), patch.object(transport, '_recover') as collect:
            with self.assertRaisesRegex(transport.TransportError, 'valid successful response') as caught:
                transport.run('cup', self.root / 'cup.jpg', execute=True)
        collect.assert_not_called()
        self.assertNotIn('secret sentinel', str(caught.exception))
        record = json.loads(next((self.root / '.grok-runs').glob('*/provenance.json')).read_text())
        self.assertEqual(record['transport_state'], 'incomplete')

    def test_session_mismatch_persisted_and_recovery_blocked(self):
        response = subprocess.CompletedProcess('grok', 0, json.dumps({'sessionId': 'wrong'}), '')
        with patch.object(transport.shutil, 'which', return_value='/bin/grok'), patch.object(
                transport.subprocess, 'run', return_value=response):
            with self.assertRaisesRegex(transport.TransportError, 'identity mismatch'):
                transport.run('cup', self.root / 'cup.jpg', execute=True)
        ledger = next((self.root / '.grok-runs').glob('*/provenance.json'))
        record = json.loads(ledger.read_text())
        self.assertEqual(record['transport_state'], 'incomplete')
        with self.assertRaisesRegex(transport.TransportError, 'identity mismatch'):
            transport.recover(ledger.parent)

    def test_changed_source_cannot_replace_recorded_hash(self):
        self.record()
        first = transport.recover(self.root)
        (self.root / 'result.png').unlink()
        self.source.write_bytes(JPEG)
        with self.assertRaisesRegex(transport.TransportError, 'changed after its hash'):
            transport.recover(self.root)
        self.assertEqual(json.loads((self.root / 'provenance.json').read_text())['output_sha256'], first['output_sha256'])

    def test_success_survives_session_cleanup_and_preserves_qc(self):
        self.record()
        result = transport.recover(self.root)
        result['qc_status'] = 'passed'
        transport.save_record(self.root, result)
        self.source.unlink()
        (self.session / 'chat_history.jsonl').unlink()
        self.assertEqual(transport.recover(self.root)['qc_status'], 'passed')

    def test_jpeg_extension_mismatch_can_be_recovered_without_generation(self):
        self.source.write_bytes(JPEG)
        self.record()
        with self.assertRaisesRegex(transport.TransportError, 'extension'):
            transport.recover(self.root)
        with patch.object(transport.subprocess, 'run') as launch:
            result = transport.recover(self.root, self.root / 'correct.jpg')
        launch.assert_not_called()
        self.assertEqual(result['image']['format'], 'jpeg')
        self.assertEqual((result['image']['width'], result['image']['height']), (1, 1))
        self.assertEqual((self.root / 'correct.jpg').read_bytes(), JPEG)
        self.assertFalse((self.root / 'result.png').exists())

    def test_changed_reference_blocks_delivery(self):
        record = self.record()
        original = self.root / 'original.png'
        original.write_bytes(png())
        record.update(reference_path=str(original), reference_sha256=transport.inspect_image(original)['sha256'])
        transport.save_record(self.root, record)
        original.write_bytes(JPEG)
        with self.assertRaisesRegex(transport.TransportError, 'reference changed'):
            transport.recover(self.root)

    def test_running_lock_blocks_recovery(self):
        self.record()
        with transport.run_lock(self.root):
            with self.assertRaisesRegex(transport.TransportError, 'still executing'):
                transport.recover(self.root)

    def test_malformed_transcript_returns_transport_error(self):
        self.record()
        (self.session / 'chat_history.jsonl').write_text('{broken')
        with self.assertRaisesRegex(transport.TransportError, 'transcript'):
            transport.recover(self.root)

    def test_foreign_session_in_ledger_is_rejected(self):
        record = self.record()
        record['session_id'] = str(uuid.uuid4())
        transport.save_record(self.root, record)
        with self.assertRaisesRegex(transport.TransportError, 'does not belong'):
            transport.recover(self.root)

    def test_lost_delivery_can_be_restored_to_new_destination(self):
        self.record()
        first = transport.recover(self.root)
        (self.root / 'result.png').unlink()
        result = transport.recover(self.root, self.root / 'restored.png')
        self.assertEqual(result['output_sha256'], first['output_sha256'])
        self.assertEqual((self.root / 'restored.png').read_bytes(), png())


if __name__ == '__main__':
    unittest.main()
