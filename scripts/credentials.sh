# Collect the Tailscale OAuth client and operator identity into .env.
info "create a Tailscale OAuth client with write scopes 'auth_keys' and 'policy_file',"
info "and attach tag:cinder to the auth_keys scope."
prompt_secret TS_OAUTH_CLIENT_ID "Tailscale OAuth client ID" "https://login.tailscale.com/admin/settings/oauth"
prompt_secret TS_OAUTH_SECRET "Tailscale OAuth client secret" "https://login.tailscale.com/admin/settings/oauth"
prompt_value  TS_OPERATOR "your tailnet identity (email) allowed to SSH into runners" ""
if confirm "enable the daily integration check (needs an Anthropic API key)?"; then
  prompt_secret ANTHROPIC_API_KEY "Anthropic API key" "https://console.anthropic.com/settings/keys"
fi
