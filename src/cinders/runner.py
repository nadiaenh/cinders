"""Workflow-side setup and bounded SSH lifetime; run only on GitHub Ubuntu."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


LIFETIME_SECONDS = 20 * 60


def validate(env):
    key = env['CINDER_PUBLIC_KEY'].strip()
    if '\n' in key or '\r' in key:
        raise ValueError('Only one SSH public key is accepted')
    parts = key.split()
    if len(parts) < 2 or parts[0] != 'ssh-ed25519':
        raise ValueError('Expected an Ed25519 public key without authorized_keys options')
    decoded = base64.b64decode(parts[1], validate=True)
    if len(decoded) != 51 or decoded[:19] != b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20':
        raise ValueError('Malformed Ed25519 public key')
    return ' '.join(parts[:2])


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def start():
    key = validate(os.environ)
    cinder_id = str(int(os.environ['GITHUB_RUN_ID']))
    if os.geteuid() != 0 or not Path('/home/runner').is_dir():
        raise ValueError('Setup requires root on a disposable GitHub Ubuntu runner')
    home = Path('/home/cinder')
    run('useradd', '--create-home', '--shell', '/bin/bash', 'cinder')
    # A non-locked account is required by sshd; password authentication remains disabled.
    run('usermod', '--password', '*', 'cinder')
    workspace = home / 'workspace'
    shutil.copytree(os.environ['GITHUB_WORKSPACE'], workspace,
                    ignore=shutil.ignore_patterns('.git', '.cinders', '__pycache__'))
    run('chown', '-R', 'cinder:cinder', str(workspace))
    config = Path('/etc/cinder')
    config.mkdir(mode=0o700)
    (config / 'authorized_keys').write_text('restrict,pty ' + key + '\n')
    run('ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(config / 'host_key'))
    address = run('tailscale', 'ip', '-4').splitlines()[0]
    (config / 'sshd_config').write_text(f'''Port 2222
ListenAddress {address}
HostKey {config}/host_key
PidFile /run/cinder-sshd.pid
AuthorizedKeysFile {config}/authorized_keys
StrictModes yes
AllowUsers cinder
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
UsePAM no
AllowAgentForwarding no
AllowTcpForwarding no
X11Forwarding no
PermitTunnel no
PermitUserEnvironment no
Subsystem sftp internal-sftp
''')
    # sshd reads authorized_keys as the login user, while only root may change it.
    config.chmod(0o755)
    (config / 'authorized_keys').chmod(0o644)
    Path('/run/sshd').mkdir(exist_ok=True)
    run('/usr/sbin/sshd', '-t', '-f', str(config / 'sshd_config'))
    run('systemd-run', '--unit=cinder-sshd', '--property=KillMode=control-group',
        f'--property=RuntimeMaxSec={LIFETIME_SECONDS}', '--property=TimeoutStopSec=5',
        '/usr/sbin/sshd', '-D', '-e', '-f', str(config / 'sshd_config'))
    run('systemctl', 'is-active', 'cinder-sshd.service')
    metadata = {'id': cinder_id, 'run_id': int(os.environ['GITHUB_RUN_ID']),
                'run_attempt': int(os.environ['GITHUB_RUN_ATTEMPT']), 'host': address,
                'port': 2222, 'user': 'cinder', 'expires_at': int(time.time()) + LIFETIME_SECONDS,
                'host_key': ' '.join((config / 'host_key.pub').read_text().split()[:2])}
    output = Path(os.environ['RUNNER_TEMP']) / 'cinder-connection'
    output.mkdir()
    (output / 'connection.json').write_text(json.dumps(metadata))


def hold():
    metadata = json.loads((Path(os.environ['RUNNER_TEMP']) / 'cinder-connection/connection.json').read_text())
    remaining = max(0, metadata['expires_at'] - time.time())
    print(f"Cinder {metadata['id']} is available for approximately {remaining:.0f}s", flush=True)
    time.sleep(remaining)


if __name__ == '__main__':
    {'validate': lambda: validate(os.environ), 'start': start, 'hold': hold}[sys.argv[1]]()
