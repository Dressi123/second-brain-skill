# Second-brain MCP server (hosted)

The vault, reachable from Claude on the iPhone and the web whether or not the
Mac is awake. Same six tools and the same helper code as the Mac servers; the
only difference is where the vault comes from.

## How it gets the vault

There is no iCloud here and no persistent disk, so the vault is rebuilt into
`/tmp` from the GitHub repo the Mac pushes to. A cheap head-sha probe decides
whether the cached copy is current, and only a genuine change costs a tarball
download. Writes commit straight back through GitHub's Contents API, so a note
captured on the phone is on GitHub the moment the tool returns; the Mac picks
it up on its next vault read.

Measured locally: ~2.0s to materialize 308 notes cold, ~0.33s warm.

## Layout

    app.py               the ASGI app: six MCP tools + the OAuth endpoints
    vault_github.py      materialize from GitHub, write back through its API
    oauth_stateless.py   OAuth 2.1 with nothing to store
    approval_page.py     the consent screen
    vault_tools.py       vendored from ../mcp-server (see sync_helpers.sh)
    helpers/             vendored from ../helpers

`vault_tools.py` and `helpers/` are copies. Run `./sync_helpers.sh` after
changing either original, then redeploy. They are vendored rather than shared
because Vercel deploys one directory, and the skill directory next door holds
`.oauth_password` and `.remote_token` -- keeping the deploy surface small and
explicit beats trusting a gitignore not to leak a credential.

## Environment variables

| Name | What it is |
| --- | --- |
| `GITHUB_TOKEN` | Fine-grained PAT, Contents read+write, scoped to the vault repo only |
| `OAUTH_SIGNING_SECRET` | Random string. Signs every token; rotating it logs every device out |
| `MCP_APPROVAL_PASSWORD` | Typed on the consent page when adding the connector |
| `PUBLIC_URL` | The production URL. Set after the first deploy so metadata advertises the right issuer |
| `VAULT_REPO` | Optional, defaults to `Dressi123/second-brain-vault` |

## Deploying

Order matters. Do not add the connector before `PUBLIC_URL` is set, or Claude
registers against whichever host served the first request.

1. `vercel deploy --prod` from this directory.
2. Set the four environment variables (below), then `vercel deploy --prod`
   again so `PUBLIC_URL` takes effect.
3. `curl -H 'X-Health-Key: <approval password>' <PUBLIC_URL>/health` and confirm
   it reports the note count.
4. Add the connector in Claude's settings using `<PUBLIC_URL>/mcp`, and enter
   the approval password on the consent page.
5. Only then retire the Mac's old server: unload
   `com.the-user.second-brain-remote-mcp` and turn off the Tailscale Funnel.

`GITHUB_TOKEN` must be a fine-grained personal access token with Contents
read+write on the vault repo and nothing else. Do not use `gh auth token` --
that is the CLI's own credential and carries far broader scopes.

## Checking it

`GET /health` reports only whether the environment variables are set. It is
unauthenticated, so it deliberately reveals nothing else and makes no GitHub
call. Send the approval password as an `X-Health-Key` header for the real
check, which materializes the vault and reports the commit and note count. A
header, not a query parameter, because query strings land in request logs.

## Known deviations from the Mac server

Both follow from having no storage, and both are deliberate:

- **No refresh-token revocation list.** A refresh token stays valid until it
  expires rather than being revocable. Rotating `OAUTH_SIGNING_SECRET`
  invalidates everything at once, which is the recovery path.
- **Authorization codes are only marked spent per instance.** They are
  PKCE-bound with S256 required, live 120 seconds, and any exchange attempt
  spends them. Replay across two instances inside that window is the residual
  gap, and it still needs the verifier.
