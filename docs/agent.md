# Setup

Run the CLI from the project directory after completing [network setup](setup.md). Replace `OWNER/REPO` with the configured repository.

# Usage

```bash
CINDER_ID=$(./cinder warmup --repo OWNER/REPO)
./cinder sync "$CINDER_ID" /absolute/path/to/project
./cinder run "$CINDER_ID" 'python3 -m unittest discover -s tests -v'
./cinder stop "$CINDER_ID"
```

Reuse the same cinder ID throughout the task. Repeat `sync` and `run` after code changes. Replace the sample test command with the project's test command.

Commands execute in `/home/cinder/workspace` under an unprivileged account. The SSH lifetime is fixed at 20 minutes. Install system dependencies in the workflow before SSH startup.

Record the remote test command and exit code in verification reports. Report success only after the test command exits successfully. Cancel the cinder after verification.
