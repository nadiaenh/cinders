"""GitHub Actions / OpenSSH cinder client. Requires gh, ssh, ssh-keygen, rsync."""
import argparse
import base64
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.cinders'
WORKFLOW = 'cinder.yml'


def command(argv, *, capture=True, input=None, timeout=30):
    return subprocess.run(argv, input=input, stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None, check=True, timeout=timeout)


def gh(*args, payload=None):
    argv = ['gh', *args]
    if payload is not None:
        argv += ['--input', '-']
    return command(argv, input=json.dumps(payload).encode() if payload is not None else None).stdout


def api(path, method='GET', payload=None):
    raw = gh('api', '-H', 'X-GitHub-Api-Version: 2026-03-10', '--method', method, path, payload=payload)
    return json.loads(raw) if raw.strip() else None


def directory(cinder_id):
    if not re.fullmatch(r'[1-9][0-9]*', cinder_id):
        raise ValueError('Invalid cinder ID')
    return STATE / cinder_id


def save(state):
    folder = directory(state['id'])
    with tempfile.NamedTemporaryFile(mode='w', dir=folder, delete=False) as handle:
        json.dump(state, handle, indent=2)
        tmp = handle.name
    os.replace(tmp, folder / 'state.json')


def load(cinder_id):
    return json.loads((directory(cinder_id) / 'state.json').read_text())


def discover(state):
    return api(f"repos/{state['repo']}/actions/runs/{state['run_id']}")


def check_run(run):
    if run and run.get('run_attempt', 1) != 1:
        raise ValueError('Workflow reruns are not supported; warm up a fresh cinder')
    if run and run['status'] == 'completed':
        raise ValueError(f"Cinder job finished: {run.get('conclusion')}. Start a new cinder.")


def validate_metadata(data, state):
    if data.get('id') != state['id'] or data.get('run_id') != state['run_id'] or data.get('run_attempt') != 1:
        raise ValueError('Connection metadata does not match this cinder/run')
    address = ipaddress.ip_address(data['host'])
    if address not in ipaddress.ip_network('100.64.0.0/10'):
        raise ValueError('Expected a Tailscale IPv4 address')
    if data.get('user') != 'cinder' or data.get('port') != 2222:
        raise ValueError('Unexpected SSH user or port')
    key = data.get('host_key', '').split()
    if len(key) != 2 or key[0] != 'ssh-ed25519':
        raise ValueError('Invalid SSH host key')
    base64.b64decode(key[1], validate=True)
    if not isinstance(data.get('expires_at'), int) or data['expires_at'] <= time.time():
        raise ValueError('Cinder has expired')
    return data


def connection(state):
    if state.get('connection'):
        return validate_metadata(state['connection'], state)
    artifacts = api(f"repos/{state['repo']}/actions/runs/{state['run_id']}/artifacts?per_page=100")
    matches = [a for a in artifacts['artifacts'] if a['name'] == f"cinder-{state['id']}" and not a['expired']]
    if not matches:
        return None
    raw = gh('api', f"repos/{state['repo']}/actions/artifacts/{matches[0]['id']}/zip")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        info = archive.getinfo('connection.json')
        if info.file_size > 16384:
            raise ValueError('Oversized connection metadata')
        data = validate_metadata(json.loads(archive.read(info)), state)
    known = directory(state['id']) / 'known_hosts'
    known.write_text(f"[{data['host']}]:2222 {data['host_key']}\n")
    state['connection'] = data
    save(state)
    return data


def ssh_args(state):
    data = validate_metadata(state['connection'], state)
    folder = directory(state['id'])
    return ['ssh', '-F', '/dev/null', '-i', str(folder / 'id_ed25519'), '-p', '2222',
            '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', f'UserKnownHostsFile={folder / "known_hosts"}', '-o', 'GlobalKnownHostsFile=/dev/null',
            '-o', 'ConnectTimeout=5', '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2',
            '-o', 'ForwardAgent=no', '-o', 'ClearAllForwardings=yes', f"cinder@{data['host']}"]


def wait_ready(state, wait):
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        run = discover(state)
        check_run(run)
        if run and connection(state):
            try:
                command(ssh_args(state) + ['true'], timeout=10)
                return
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                pass
        time.sleep(3)
    raise TimeoutError(f"Cinder not ready after {wait}s. Check status or stop cinder {state['id']}.")


def warmup(args):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repo):
        raise ValueError('--repo must be OWNER/REPO')
    STATE.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix='pending-', dir=STATE))
    command(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(folder / 'id_ed25519')])
    print(f'Starting cinder; local key directory: {folder}', file=sys.stderr, flush=True)
    result = api(f'repos/{args.repo}/actions/workflows/{WORKFLOW}/dispatches', method='POST',
                 payload={'ref': args.ref, 'inputs': {'ssh_public_key': (folder / 'id_ed25519.pub').read_text().strip()}})
    if not isinstance(result, dict) or not isinstance(result.get('workflow_run_id'), int):
        raise ValueError('Dispatch returned no run ID. Inspect GitHub Actions before retrying; the job may have started.')
    cinder_id = str(result['workflow_run_id'])
    destination = directory(cinder_id)
    if destination.exists():
        raise ValueError(f'Local state already exists for run {cinder_id}; new key remains in {folder}')
    folder.rename(destination)
    state = {'id': cinder_id, 'run_id': result['workflow_run_id'], 'url': result['html_url'],
             'repo': args.repo, 'ref': args.ref, 'created_at': int(time.time())}
    save(state)
    print(f'Warming cinder {cinder_id}; state: {destination}', file=sys.stderr, flush=True)
    wait_ready(state, args.wait)
    print(cinder_id)


def ready(cinder_id):
    state = load(cinder_id)
    run = discover(state)
    check_run(run)
    if not run or not connection(state):
        raise ValueError('Cinder is still starting; use status and retry')
    return state


def stop(state, wait):
    run = discover(state)
    if not run:
        raise ValueError('Run not visible yet; retry stop shortly using the same ID')
    if run['status'] != 'completed':
        try:
            api(f"repos/{state['repo']}/actions/runs/{run['id']}/cancel", method='POST')
        except subprocess.CalledProcessError:
            run = discover(state)
            if run['status'] != 'completed':
                raise
    deadline = time.monotonic() + wait
    while run['status'] != 'completed' and time.monotonic() < deadline:
        time.sleep(2)
        run = discover(state)
    if run['status'] != 'completed':
        raise TimeoutError(f"Cancellation requested; not yet complete. Check {state['url']}")
    print(json.dumps({'id': state['id'], 'status': 'completed', 'conclusion': run.get('conclusion')}))


def parser():
    p = argparse.ArgumentParser(description='Warm up a cinder. Run your checks over SSH. Expires after 20 minutes.')
    sub = p.add_subparsers(dest='action', required=True)
    warm = sub.add_parser('warmup', help='Dispatch a cinder and wait for SSH readiness')
    warm.add_argument('--repo', required=True, help='OWNER/REPO containing cinder.yml')
    warm.add_argument('--ref', default='main', help='Published workflow ref (default: main)')
    warm.add_argument('--wait', type=int, default=600, help='Readiness wait in seconds')
    for action in ('status', 'run', 'ssh', 'sync', 'stop'):
        child = sub.add_parser(action)
        child.add_argument('id', help='Cinder ID returned by warmup')
        if action == 'run':
            child.add_argument('command', help='One quoted shell command, executed in ~/workspace')
        if action == 'sync':
            child.add_argument('source', nargs='?', default='.', help='Directory to copy into ~/workspace')
        if action == 'stop':
            child.add_argument('--wait', type=int, default=90)
    return p


def main():
    args = parser().parse_args()
    try:
        if args.action == 'warmup':
            warmup(args)
        elif args.action == 'status':
            state = load(args.id)
            run = discover(state)
            print(json.dumps({'id': args.id, 'run_id': state.get('run_id'), 'url': state.get('url'),
                              'status': run['status'] if run else 'pending-discovery',
                              'conclusion': run.get('conclusion') if run else None,
                              'expires_at': state.get('connection', {}).get('expires_at')}, indent=2))
        elif args.action == 'stop':
            stop(load(args.id), args.wait)
        else:
            state = ready(args.id)
            ssh = ssh_args(state)
            if args.action == 'run':
                remote = 'cd /home/cinder/workspace && bash -lc ' + shlex.quote(args.command)
                sys.exit(subprocess.call(ssh + [remote]))
            elif args.action == 'ssh':
                sys.exit(subprocess.call(ssh[:-1] + ['-t', ssh[-1], 'cd /home/cinder/workspace && exec bash -l']))
            else:
                source = Path(args.source).resolve()
                if not source.is_dir():
                    raise ValueError('sync source must be a directory')
                transport = shlex.join(ssh[:-1])
                sys.exit(subprocess.call(['rsync', '-az', '--exclude=.git/', '--exclude=.cinders/',
                                          '-e', transport, str(source) + '/', ssh[-1] + ':/home/cinder/workspace/']))
    except KeyboardInterrupt:
        print('\nInterrupted. Use the printed ID with stop. If dispatch returned no ID, inspect GitHub Actions before retrying.', file=sys.stderr)
        sys.exit(130)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        detail = exc.stderr.decode(errors='replace').strip() if isinstance(exc, subprocess.CalledProcessError) and exc.stderr else str(exc)
        print(f'cinder: {detail}', file=sys.stderr)
        sys.exit(1)
