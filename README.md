<p align="center"> <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+"></a> <a href=".github/workflows/cinder.yml"><img src="https://img.shields.io/badge/GitHub_Actions-2088FF?logo=githubactions&logoColor=white" alt="GitHub Actions VM"></a> <a href="https://tailscale.com"><img src="https://img.shields.io/badge/Tailscale-242424?logo=tailscale&logoColor=white" alt="SSH via Tailscale"></a> <a href=".github/workflows/integration.yml"><img src="https://github.com/nadiaenh/cinders/actions/workflows/integration.yml/badge.svg" alt="Integration"></a> </p>

**cinders** is a GitHub-Actions-based ephemeral VM service for agents. Your agent can `warmup` a VM (dispatch a workflow), `sync` its working tree, and `run` commands against it. Runners live under your tailnet and are held open for 20 minutes.

<p align="center"><img src="assets/cinderella.gif" alt="Cinderella scrubbing a floor"></p>

## Setup

Requires macOS with [Homebrew](https://brew.sh), a GitHub repository to push this to, and a Tailscale account.

```bash
git clone https://github.com/nadiaenh/cinders.git
cd cinders
./setup.sh
```

## Usage

```bash
# Start a VM - this returns the run ID once SSH becomes available.
CINDER_ID=$(./cinder warmup --repo "$OWNER/$REPO" --ref main)

# Copy the working tree into the VM and run some imaginary unit tests.
./cinder sync "$CINDER_ID" .
./cinder run "$CINDER_ID" 'python3 -m unittest discover -s tests -v'

# Take a peek, drop into a shell, or kill the VM.
./cinder status "$CINDER_ID"
./cinder ssh "$CINDER_ID"
./cinder stop "$CINDER_ID"

# Local unit tests.
python3 -m unittest discover -s tests -v
```

## Demo

![cinder command-line help](assets/cli-help.svg)
