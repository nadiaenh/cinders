# Add tag:cinder ownership and a tcp:2222 grant for the operator to the tailnet policy.
id=$(env_get TS_OAUTH_CLIENT_ID)
secret=$(env_get TS_OAUTH_SECRET)
op=$(env_get TS_OPERATOR)
acl=$(mktemp)

confirm "patch your tailnet ACL now (adds tag:cinder owner + tcp:2222 grant for $op)?" \
  || { warn "skipped; the README lists the manual policy steps"; return 0; }

token=$(curl -sf https://api.tailscale.com/api/v2/oauth/token \
  -d "client_id=$id" -d "client_secret=$secret" | jq -r .access_token)
[ -n "$token" ] && [ "$token" != null ] || fail "could not exchange the OAuth client for an API token"

# Fetch the policy, add the tag owner and grant, write it back (drops HuJSON comments).
curl -sf -H "Authorization: Bearer $token" -H 'Accept: application/json' \
  https://api.tailscale.com/api/v2/tailnet/-/acl \
  | jq --arg op "$op" '.tagOwners["tag:cinder"] = ["autogroup:admin"] | .grants = ((.grants // []) + [{"src":[$op],"dst":["tag:cinder"],"ip":["tcp:2222"]}])' \
  > "$acl" || fail "could not read the current tailnet policy"

curl -sf -X POST -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  --data-binary "@$acl" https://api.tailscale.com/api/v2/tailnet/-/acl >/dev/null \
  || fail "could not update the tailnet policy"
ok "tailnet policy updated"
