# The CLI machine must be on the tailnet to reach the ephemeral runners.
have tailscale || fail "Tailscale CLI not installed" "run: brew install tailscale"
if quiet tailscale status; then
  ok "this machine is on the tailnet"
else
  info "this machine is not on your tailnet yet"
  confirm "run 'sudo tailscale up' now?" || fail "Tailscale is required" "run: sudo tailscale up"
  sudo tailscale up
  quiet tailscale status || fail "still not connected to the tailnet"
  ok "joined the tailnet"
fi
