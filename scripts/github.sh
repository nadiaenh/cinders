# Push the workflow secrets to the repo.
have gh || fail "GitHub CLI not installed" "run: brew install gh"
quiet gh auth status || fail "GitHub CLI is not authenticated" "run: gh auth login"
repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner) \
  || fail "not inside a GitHub repo" "push this repo to GitHub first"
ok "target repo: $repo"
for key in TS_OAUTH_CLIENT_ID TS_OAUTH_SECRET ANTHROPIC_API_KEY; do
  [ -n "$(env_get "$key")" ] && push_secret "$key"
done
