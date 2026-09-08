# Network setup

Cinders join the tailnet as ephemeral nodes tagged `tag:cinder`. OpenSSH listens only on the Tailscale IPv4 address at TCP 2222. All steps below are CLI except OAuth client creation, which is console-only.

## 1. Connect the CLI machine

```bash
brew install tailscale
sudo tailscale up
tailscale status   # confirm the machine is logged in
```

## 2. Create the OAuth client (console-only)

At <https://login.tailscale.com/admin/settings/oauth>, create a client with write scopes `auth_keys` and `policy_file`, and attach `tag:cinder` to the `auth_keys` scope. Copy the client ID and secret.

```bash
export TS_ID='<client-id>'
export TS_SECRET='<client-secret>'
gh secret set TS_OAUTH_CLIENT_ID --repo OWNER/REPO --body "$TS_ID"
gh secret set TS_OAUTH_SECRET   --repo OWNER/REPO --body "$TS_SECRET"
```

## 3. Push the tailnet policy

The OAuth client mints its own short-lived API token, then patches the policy. `OPERATOR` is the CLI operator identity from `tailscale status --json | jq -r .Self.UserID` resolved to an email, or the login email shown in the admin console.

```bash
export OPERATOR='operator@example.com'

TOKEN=$(curl -sf https://api.tailscale.com/api/v2/oauth/token \
  -d "client_id=$TS_ID" -d "client_secret=$TS_SECRET" | jq -r .access_token)

curl -sf -H "Authorization: Bearer $TOKEN" -H 'Accept: application/json' \
  https://api.tailscale.com/api/v2/tailnet/-/acl \
| jq --arg op "$OPERATOR" '
    .tagOwners["tag:cinder"] = ["autogroup:admin"]
  | .grants = ((.grants // []) + [{"src":[$op],"dst":["tag:cinder"],"ip":["tcp:2222"]}])
  ' > /tmp/cinder-acl.json

curl -sf -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  --data-binary @/tmp/cinder-acl.json \
  https://api.tailscale.com/api/v2/tailnet/-/acl
```

Grants are additive. Posting as `application/json` drops any HuJSON comments in the existing policy; edit the policy in the console instead if those comments matter. Remove conflicting broad access rules so CLI reach to cinders is limited to TCP 2222 and cinders cannot open connections to other tailnet devices. OpenSSH uses public-key authentication; no Tailscale SSH policy is required.

# Live checks

Publish `.github/workflows/cinder.yml` and configure the repository secrets before dispatching a cinder:

```bash
CINDER_ID=$(./cinder warmup --repo OWNER/REPO)
./cinder run "$CINDER_ID" 'printf "remote verification\n"; id; pwd'
./cinder run "$CINDER_ID" 'exit 7'
echo "$?" # expect 7
./cinder sync "$CINDER_ID" .
./cinder run "$CINDER_ID" 'python3 -m unittest discover -s tests -v'
./cinder stop "$CINDER_ID"
./cinder status "$CINDER_ID"
```

For an expiry check, start a fresh cinder and run `sleep 1500`. SSH must disconnect at expiry, including during an active command. Check the GitHub job status afterward.

# Troubleshooting

If warmup times out, stderr contains the cinder ID. Run `./cinder status CINDER_ID` to obtain the GitHub run URL, then inspect the failing step, local Tailscale connection, tailnet policy, and repository secrets.

If dispatch is interrupted before returning an ID, inspect the repository's Actions page and cancel the run before repeating dispatch. The private key remains in the local `pending-*` directory reported by the CLI.
