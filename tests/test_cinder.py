import base64
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from cinders import cli as cinder, runner

CINDER_ID = '123'
KEY = 'ssh-ed25519 ' + base64.b64encode(b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20' + b'x' * 32).decode()


class CinderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patch = patch.object(cinder, 'STATE', Path(self.tmp.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        cinder.directory(CINDER_ID).mkdir()
        self.state = {'id': CINDER_ID, 'repo': 'owner/repo', 'run_id': 123}
        self.metadata = {'id': CINDER_ID, 'run_id': 123, 'run_attempt': 1, 'host': '100.64.1.2',
                         'port': 2222, 'user': 'cinder', 'host_key': KEY, 'expires_at': int(time.time()) + 600}

    def test_metadata_rejects_wrong_identity_expiry_address_and_key(self):
        for change in ({'id': '456'}, {'run_id': 999}, {'run_attempt': 2},
                       {'host': '127.0.0.1'}, {'host': '-oProxyCommand=x'},
                       {'expires_at': 0}, {'host_key': 'invalid'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                cinder.validate_metadata(self.metadata | change, self.state)

    def test_download_pins_host_key_from_matching_artifact(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('connection.json', json.dumps(self.metadata))
        artifacts = {'artifacts': [{'id': 5, 'name': 'other', 'expired': False},
                                  {'id': 6, 'name': 'cinder-' + CINDER_ID, 'expired': False}]}
        with patch.object(cinder, 'api', return_value=artifacts), patch.object(cinder, 'gh', return_value=stream.getvalue()) as gh:
            cinder.connection(self.state)
        self.assertIn('/6/zip', gh.call_args.args[1])
        self.assertEqual((cinder.directory(CINDER_ID) / 'known_hosts').read_text(), f'[100.64.1.2]:2222 {KEY}\n')
        self.assertEqual(cinder.load(CINDER_ID)['connection'], self.metadata)

    def test_missing_artifact_is_pending(self):
        with patch.object(cinder, 'api', return_value={'artifacts': []}):
            self.assertIsNone(cinder.connection(self.state))

    def test_discovery_fetches_exact_generated_run_id(self):
        with patch.object(cinder, 'api', return_value={'id': 123}) as api:
            self.assertEqual(cinder.discover(self.state)['id'], 123)
        api.assert_called_once_with('repos/owner/repo/actions/runs/123')

    def test_completed_or_rerun_rejected(self):
        for run in ({'status': 'completed', 'conclusion': 'failure'}, {'status': 'in_progress', 'run_attempt': 2}):
            with self.assertRaises(ValueError):
                cinder.check_run(run)

    def test_ssh_enforces_host_identity_and_no_forwarding(self):
        self.state['connection'] = self.metadata
        args = cinder.ssh_args(self.state)
        self.assertIn('StrictHostKeyChecking=yes', args)
        self.assertIn('ForwardAgent=no', args)
        self.assertIn('IdentitiesOnly=yes', args)
        self.assertEqual(args[-1], 'cinder@100.64.1.2')

    def test_run_preserves_shell_command_and_exit_code(self):
        self.state['connection'] = self.metadata
        script = '''printf '%s\\n' "hello world"; exit 7'''
        argv = ['cinder', 'run', CINDER_ID, script]
        with patch('sys.argv', argv), patch.object(cinder, 'ready', return_value=self.state), patch.object(cinder.subprocess, 'call', return_value=7) as call:
            with self.assertRaises(SystemExit) as result:
                cinder.main()
        self.assertEqual(result.exception.code, 7)
        import shlex
        remote = call.call_args.args[0][-1]
        self.assertEqual(shlex.split(remote.split('&& ', 1)[1]), ['bash', '-lc', script])

    def test_stop_completed_is_idempotent(self):
        with patch.object(cinder, 'discover', return_value={'id': 123, 'status': 'completed'}), patch.object(cinder, 'api') as api, contextlib.redirect_stdout(io.StringIO()):
            cinder.stop(self.state, 5)
        api.assert_not_called()

    def test_stop_waits_for_exact_run(self):
        states = [{'id': 123, 'status': 'in_progress'}, {'id': 123, 'status': 'completed', 'conclusion': 'cancelled'}]
        with patch.object(cinder, 'discover', side_effect=states), patch.object(cinder, 'api') as api, patch.object(cinder.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
            cinder.stop(self.state, 5)
        api.assert_called_once_with('repos/owner/repo/actions/runs/123/cancel', method='POST')

    def test_stop_accepts_completion_during_cancel(self):
        states = [{'id': 123, 'status': 'in_progress'}, {'id': 123, 'status': 'completed'}]
        with patch.object(cinder, 'discover', side_effect=states), patch.object(cinder, 'api', side_effect=subprocess.CalledProcessError(1, 'gh')), contextlib.redirect_stdout(io.StringIO()):
            cinder.stop(self.state, 5)

    def test_sync_quotes_transport_paths_with_spaces(self):
        self.state['connection'] = self.metadata
        with tempfile.TemporaryDirectory(prefix='cinder test ') as folder:
            with patch.object(cinder, 'STATE', Path(folder)), patch('sys.argv', ['cinder', 'sync', CINDER_ID, folder]), patch.object(cinder, 'ready', return_value=self.state), patch.object(cinder.subprocess, 'call', return_value=0) as call:
                with self.assertRaises(SystemExit) as result:
                    cinder.main()
            self.assertEqual(result.exception.code, 0)
            argv = call.call_args.args[0]
            import shlex
            transport = shlex.split(argv[argv.index('-e') + 1])
            self.assertEqual(transport[transport.index('-i') + 1], str(Path(folder) / CINDER_ID / 'id_ed25519'))
            self.assertEqual(argv[-1], 'cinder@100.64.1.2:/home/cinder/workspace/')

    def test_warmup_generates_real_key_and_dispatches_only_public_key(self):
        real_command = cinder.command
        dispatches = []
        def fake_dispatch(argv, **kwargs):
            if argv[0] == 'gh':
                dispatches.append((argv, json.loads(kwargs['input'])))
                return subprocess.CompletedProcess(argv, 0, json.dumps({'workflow_run_id': 456, 'html_url': 'https://github.com/owner/repo/actions/runs/456'}).encode(), b'')
            return real_command(argv, **kwargs)
        args = cinder.parser().parse_args(['warmup', '--repo', 'owner/repo'])
        with patch.object(cinder, 'command', side_effect=fake_dispatch), patch.object(cinder, 'wait_ready'), contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
            cinder.warmup(args)
        identity = out.getvalue().strip()
        folder = cinder.directory(identity)
        self.assertEqual((folder / 'id_ed25519').stat().st_mode & 0o777, 0o600)
        self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
        argv, payload = dispatches[0]
        self.assertEqual(identity, '456')
        self.assertIn('X-GitHub-Api-Version: 2026-03-10', argv)
        self.assertEqual(set(payload), {'ref', 'inputs'})
        self.assertEqual(set(payload['inputs']), {'ssh_public_key'})
        runner.validate({'CINDER_PUBLIC_KEY': payload['inputs']['ssh_public_key']})
        self.assertNotIn('PRIVATE', json.dumps(payload))

    def test_readiness_requires_ssh(self):
        run = {'status': 'in_progress'}
        with patch.object(cinder, 'discover', return_value=run), patch.object(cinder, 'connection', return_value=self.metadata), patch.object(cinder, 'ssh_args', return_value=['ssh']), patch.object(cinder, 'command', side_effect=[subprocess.CalledProcessError(255, 'ssh'), object()]) as cmd, patch.object(cinder.time, 'sleep'):
            cinder.wait_ready(self.state, 10)
        self.assertEqual(cmd.call_count, 2)

    def test_dispatch_without_id_does_not_retry_or_claim_readiness(self):
        args = cinder.parser().parse_args(['warmup', '--repo', 'owner/repo'])
        with patch.object(cinder, 'api', return_value=None) as api, patch.object(cinder, 'wait_ready') as ready, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'job may have started'):
                cinder.warmup(args)
        self.assertEqual(api.call_count, 1)
        ready.assert_not_called()
        pending = list(cinder.STATE.glob('pending-*'))
        self.assertEqual(len(pending), 1)
        self.assertTrue((pending[0] / 'id_ed25519').is_file())

    def test_runner_inputs(self):
        env = {'CINDER_PUBLIC_KEY': KEY}
        self.assertEqual(runner.validate(env), KEY)
        for change in ({'CINDER_PUBLIC_KEY': 'command="x" ' + KEY}, {'CINDER_PUBLIC_KEY': KEY + '\n' + KEY},
                       {'CINDER_PUBLIC_KEY': 'ssh-ed25519 eA=='}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                runner.validate(env | change)

    def test_invalid_cinder_path(self):
        with self.assertRaises(ValueError):
            cinder.directory('../../outside')


if __name__ == '__main__':
    unittest.main()
