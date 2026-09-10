#!/usr/bin/env bash
cd "$(dirname "$0")"
source scripts/common.sh

step "1. Install tools"
source scripts/homebrew.sh

step "2. Install the CLI"
source scripts/python.sh

step "3. Tailscale"
source scripts/tailscale.sh

step "4. Credentials"
source scripts/credentials.sh

step "5. GitHub secrets"
source scripts/github.sh

step "6. Tailnet policy"
source scripts/policy.sh

step "Setup complete"
echo "  push .github/workflows/ to the default branch, then run:"
echo "  ./cinder warmup --repo ${repo:-OWNER/REPO}"
