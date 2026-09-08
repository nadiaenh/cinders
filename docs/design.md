# Lifecycle

`warmup` generates a local Ed25519 login keypair and dispatches `cinder.yml` with the login public key. The cinder ID is the workflow run ID returned by the [GitHub dispatch API](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event), using API version `2026-03-10`. The CLI stores the ID, downloads connection metadata, pins the SSH host key, and verifies SSH readiness before returning.

The workflow uses a GitHub-hosted `ubuntu-24.04` runner, copies the selected ref into `/home/cinder/workspace` without `.git`, starts OpenSSH, uploads connection metadata, and holds the job open. Availability of the finalized [connection artifact](https://github.com/actions/upload-artifact) before job completion requires a live integration check.

The fixed 20-minute lifetime starts with the SSH service, before metadata upload. Commands do not extend the lifetime. `RuntimeMaxSec` stops the service; `KillMode=control-group` closes sessions and child processes. Cleanup also stops the service. The overall job timeout is 30 minutes, so slow setup can reduce available SSH time. Tailscale logs out the ephemeral node at job completion. Metadata expiry provides an approximate client check; the service timer enforces the SSH deadline.

`stop` cancels the exact GitHub run and waits for completion; completed runs require no action. `status` reports workflow state without probing SSH. Workflow reruns are unsupported.

# Authentication and access

Tailscale provides the encrypted private network; OpenSSH authenticates connections. The CLI uses `gh` for GitHub authentication. The workflow has `contents: read` permission, and checkout does not persist credentials.

The CLI stores the login private key at `.cinders/RUN_ID/id_ed25519` with mode 0600 inside a directory with mode 0700. Only the login public key reaches GitHub. Local account permissions do not isolate the key from processes running under the same account or from administrators.

The cinder generates a separate SSH host keypair. Connection metadata contains the Tailscale IP, public host key, cinder/run IDs, and expiry; no private keys are included. GitHub artifact access establishes trust in the advertised host key. An unexpected host key fails the connection.

Remote commands stream through SSH and return the remote exit status. The CLI disables host-key guessing, agent forwarding, and connection sharing from SSH configuration.

# Scope and validation

`sync` transfers unpublished changes into the remote workspace. The cinder account cannot install system packages or run Docker. Dependency snapshots, caching, per-command artifacts, idle extension, a hosted API, and automated agent installation are unsupported. Local agents invoke the CLI without placing model API credentials on the cinder. The runner is not an adversarial isolation environment.

Unit tests cover dispatch correlation, metadata validation, host-key pinning, SSH readiness, command quoting, exit propagation, runner input validation, and cancellation. Tests do not boot Ubuntu, authenticate over SSH, or verify GitHub/Tailscale integration. The [live checks](setup.md#live-checks) validate integration after publication.
