"""Second-brain MCP server, hosted off the Mac.

Same six tools as the Mac servers, same helper code, same output -- the only
difference is where the vault comes from. Here it is rebuilt into /tmp from
the GitHub repo the Mac pushes to, and writes commit straight back through
GitHub's API. That is what lets Claude on the iPhone reach the vault whether
or not the Mac is awake, which is the entire point of this file.

Stateless on purpose: no sessions, no token store, JSON responses rather than
long-lived streams, so any instance can serve any request.
"""
import os
import sys
from pathlib import Path
from urllib.parse import urlencode, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Point the shared vault code at this host's materialized copy BEFORE importing
# it: the helper modules capture the vault location at import time.
os.environ.setdefault("SECOND_BRAIN_VAULT", "/tmp/vault")
os.environ.setdefault("SECOND_BRAIN_HELPERS", str(HERE / "helpers"))

from mcp.server import MCPServer                      # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402
from starlette.requests import Request                # noqa: E402
from starlette.responses import JSONResponse, RedirectResponse, Response  # noqa: E402

import oauth_stateless as oauth                       # noqa: E402
import vault_github as gh                             # noqa: E402
import vault_tools as vt                              # noqa: E402
from approval_page import APPROVAL_PAGE               # noqa: E402

# vault_tools syncs a local git clone on the Mac. There is none here, and its
# guard already no-ops -- but say so explicitly rather than relying on a path
# that happens not to exist.
vt.GIT_DIR = Path("/nonexistent")

PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")


def _issuer(request: Request) -> str:
    """Prefer the configured URL; fall back to the host actually serving us,
    so a preview deployment advertises itself rather than production."""
    if PUBLIC_URL:
        return PUBLIC_URL
    return f"https://{request.headers.get('host', '')}"


mcp = MCPServer(
    "second-brain",
    instructions=(
        "Your second brain: an Obsidian vault of plain markdown notes.\n\n"
        "START WITH vault_index for any question about what he has previously "
        "worked on, decided, or written down. It returns the whole curated vault "
        "as one compact map, and picking the right note from it by meaning beats "
        "guessing keywords. search_notes is literal matching and is the drill-down "
        "for a phrase you already know, not the way to discover anything.\n\n"
        "Treat the vault as an extension of your own memory, and let it win over "
        "your own recollection when they disagree -- it reflects what is true now.\n\n"
        "THIS server reaches the vault over the network, through the copy on "
        "GitHub. It exists so Claude on a phone or the web can read the vault "
        "while the Mac is asleep. If a second-brain server running locally on the "
        "Mac is also connected, PREFER THAT ONE for every call: it reads the vault "
        "directly off disk, so it is faster and never a sync behind. Use this one "
        "only when no local server is available."
    ),
)


def _fresh() -> None:
    """Make this instance's vault copy current before reading it."""
    gh.ensure_vault()


@mcp.tool()
def vault_index(include_archive: bool = False, hub: str | None = None) -> str:
    """START HERE for any question about what the user has previously worked on,
    decided, or written down. Returns a compact map of the vault -- every note's
    path, hub, tags, and one-line description, grouped under its project/topic
    hub -- in a single call (~3k tokens for the curated tier).

    Read the descriptions and pick the note that answers the question by
    MEANING, then call read_note on its path. Do NOT reach for search_notes
    first: that is literal keyword matching and silently misses notes whose
    wording differs from the question (measured on a real question: 3 of 4
    natural phrasings returned nothing, while the right note was obvious from
    this index).

    include_archive=True adds ~250 historical bulk-export conversations
    (~11k tokens). Their descriptions are only titles, but title + hub + tags
    is enough to find things: measured 14/14 on questions sharing no wording
    with the target note, including six that had to be told apart from
    near-identical neighbours. So when the curated tier does not answer a
    question, come back here with include_archive=True BEFORE reaching for
    search_notes. hub='<id>' narrows to one project/topic.

    REMOTE COPY. If a local "second-brain" server is also connected -- meaning
    you are on the Mac -- call ITS version of this tool instead. It reads the
    vault straight off disk, so it is faster and never a moment behind. Use
    this one only when no local second-brain server is present."""
    _fresh()
    return vt.vault_index(include_archive=include_archive, hub=hub)


@mcp.tool()
def search_notes(query: str, regex: bool = False, limit: int = 20) -> str:
    """Full-text drill-down: find which notes contain a specific literal string
    or regex, with a short excerpt per match. This is NOT the tool for
    discovery -- call vault_index first to find the right note by meaning.

    Use this when you already know the phrasing you want (an exact error
    message, a command, a person's name, a specific term), or to dig into the
    bulk-export archive tier where vault_index only has titles. Literal
    matching, one hit per file -- if it returns nothing, the note may still
    exist under different wording, so check vault_index before concluding
    anything is absent.

    REMOTE COPY. If a local "second-brain" server is also connected -- meaning
    you are on the Mac -- call ITS version of this tool instead. It reads the
    vault straight off disk, so it is faster and never a moment behind. Use
    this one only when no local second-brain server is present."""
    _fresh()
    return vt.search_notes(query, regex=regex, limit=limit)


@mcp.tool()
def list_taxonomy() -> str:
    """Cheap (~200 token) list of just the valid project/topic IDs and their
    display names, scanned live. Use this to VALIDATE an id before writing or
    tagging a note. To explore what's actually in those hubs, call vault_index
    instead -- it includes everything this returns plus each hub's notes.

    REMOTE COPY. If a local "second-brain" server is also connected -- meaning
    you are on the Mac -- call ITS version of this tool instead. It reads the
    vault straight off disk, so it is faster and never a moment behind. Use
    this one only when no local second-brain server is present."""
    _fresh()
    return vt.list_taxonomy()


@mcp.tool()
def read_note(path: str) -> str:
    """Read the full content of one note by its vault-relative path, e.g.
    'Projects/FakeOut (ML Fraud Detection).md' -- as returned by vault_index or
    search_notes.

    REMOTE COPY. If a local "second-brain" server is also connected -- meaning
    you are on the Mac -- call ITS version of this tool instead. It reads the
    vault straight off disk, so it is faster and never a moment behind. Use
    this one only when no local second-brain server is present."""
    _fresh()
    return vt.read_note(path)


@mcp.tool()
def capture_note(title: str, body: str, tags: list[str] | None = None) -> str:
    """Capture a quick note into the vault's Inbox for later triage.

    Mobile/web has no end-of-session event to trigger this automatically, so
    treat it as something to call PROACTIVELY, unprompted, near the end of
    a conversation that produced something worth keeping -- a decision, an
    answer the user will want again, a plan, a fact about their life or work --
    not only when he explicitly says 'save this' or 'remember this'. The
    bar is simple: will he want to find this again? If yes, just capture
    it; don't wait to be asked, but don't capture trivial one-off
    exchanges either.

    NOT for full project/topic session summaries, which follow a stricter
    taxonomy-aware convention that Claude Code's second-brain skill handles
    separately. Always writes a uniquely named file (date + time + slug,
    with a numeric suffix on collision), so concurrent captures from
    different devices never overwrite each other.

    REMOTE COPY. If a local "second-brain" server is also connected -- meaning
    you are on the Mac -- call ITS version of this tool instead. It reads the
    vault straight off disk, so it is faster and never a moment behind. Use
    this one only when no local second-brain server is present."""
    _fresh()
    rel, content = vt.render_capture(title, body, tags=tags, source="claude-remote")
    gh.put_file(rel, content, f"capture from Claude (remote): {title[:60]}")
    return f"Saved to {rel}"


@mcp.tool()
def write_note(path: str, content: str) -> str:
    """Create or overwrite one note at a specific vault-relative path with the
    given full content. For a NEW ad hoc capture, prefer capture_note (handles
    unique filenames and frontmatter automatically) -- use this to update an
    EXISTING note (e.g. adding a fact to a project hub) or to create a new note
    at a specific, deliberate path. Refuses paths that escape the vault, and
    refuses to write into 'Claude Archive/Bulk export/' (a read-only historical
    archive of imported conversations -- never modify it).

    REMOTE COPY. If a local "second-brain" server is also connected -- meaning
    you are on the Mac -- call ITS version of this tool instead. It reads the
    vault straight off disk, so it is faster and never a moment behind. Use
    this one only when no local second-brain server is present."""
    _fresh()
    problem = vt.check_write_path(path)
    if problem:
        return problem
    gh.put_file(path, content, f"update from Claude (remote): {path}")
    return f"Wrote {path}"


# ---- OAuth 2.1 endpoints (see oauth_stateless.py) --------------------------


@mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
@mcp.custom_route("/.well-known/oauth-protected-resource/mcp", methods=["GET"])
async def protected_resource_metadata(request: Request) -> Response:
    issuer = _issuer(request)
    return JSONResponse({"resource": f"{issuer}/mcp", "authorization_servers": [issuer]})


@mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
async def authorization_server_metadata(request: Request) -> Response:
    issuer = _issuer(request)
    return JSONResponse({
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "registration_endpoint": f"{issuer}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    })


@mcp.custom_route("/register", methods=["POST"])
async def register_client(request: Request) -> Response:
    body = await request.json()
    redirect_uris = body.get("redirect_uris") or []
    if not redirect_uris:
        return JSONResponse(
            {"error": "invalid_client_metadata", "error_description": "redirect_uris required"},
            status_code=400,
        )
    client_name = body.get("client_name", "Unnamed client")
    return JSONResponse({
        "client_id": oauth.register_client(redirect_uris, client_name),
        "redirect_uris": redirect_uris,
        "client_name": client_name,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    })


@mcp.custom_route("/authorize", methods=["GET", "POST"])
async def authorize(request: Request) -> Response:
    params = dict(request.query_params)
    password = None
    if request.method == "POST":
        form = await request.form()
        params.update({k: v for k, v in form.items() if k != "password"})
        password = form.get("password", "")

    client = oauth.get_client(params.get("client_id", ""))
    redirect_uri = params.get("redirect_uri", "")
    if client is None or redirect_uri not in client["redirect_uris"]:
        return Response("Unknown client or redirect_uri.", status_code=400)

    if request.method == "GET":
        return Response(
            APPROVAL_PAGE.format(client_name=client["client_name"], error_html=""),
            media_type="text/html",
        )

    if not oauth.check_password(password):
        return Response(
            APPROVAL_PAGE.format(
                client_name=client["client_name"],
                error_html='<div class="error">Incorrect password.</div>',
            ),
            status_code=401,
            media_type="text/html",
        )

    code = oauth.create_auth_code(
        params.get("client_id", ""),
        redirect_uri,
        params.get("code_challenge", ""),
        params.get("code_challenge_method", "S256"),
    )
    query = urlencode({"code": code, "state": params.get("state", "")})
    return RedirectResponse(f"{redirect_uri}?{query}", status_code=302)


@mcp.custom_route("/token", methods=["POST"])
async def token(request: Request) -> Response:
    form = await request.form()
    grant_type = form.get("grant_type")

    if grant_type == "authorization_code":
        entry = oauth.consume_auth_code(form.get("code", ""))
        if entry is None:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        if entry["redirect_uri"] != form.get("redirect_uri", ""):
            return JSONResponse(
                {"error": "invalid_grant", "error_description": "redirect_uri mismatch"},
                status_code=400,
            )
        if not oauth.verify_pkce(
            form.get("code_verifier", ""), entry["code_challenge"], entry["code_challenge_method"]
        ):
            return JSONResponse(
                {"error": "invalid_grant", "error_description": "PKCE verification failed"},
                status_code=400,
            )
        access, refresh = oauth.issue_tokens(entry["client_id"])

    elif grant_type == "refresh_token":
        rotated = oauth.rotate_refresh_token(form.get("refresh_token", ""))
        if rotated is None:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        access, refresh = rotated

    else:
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    return JSONResponse({
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": oauth.ACCESS_TOKEN_TTL,
        "refresh_token": refresh,
    })


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    """Deployment smoke test, deliberately thin without the key.

    Anyone who finds the URL can reach this, so by default it says only
    whether the environment is configured -- no repo name, no commit, and no
    call to GitHub, which would otherwise be an unauthenticated way to burn
    the API rate limit.

    Send the approval password in an X-Health-Key header for the full check,
    which materializes the vault. A header rather than a query parameter
    because query strings end up in request logs, and this one is a password.
    """
    configured = {
        "github_token": bool(gh.TOKEN),
        "signing_secret": bool(oauth.SECRET),
        "approval_password": bool(oauth.PASSWORD),
    }
    if not oauth.check_password(request.headers.get("x-health-key", "")):
        return JSONResponse({"ok": all(configured.values()), "configured": configured})

    try:
        vault = gh.ensure_vault()
        return JSONResponse({
            "ok": True,
            "configured": configured,
            "repo": gh.REPO,
            "commit": gh._cached_sha(),
            "notes": len(list(vault.rglob("*.md"))),
        })
    except Exception as exc:                       # surface misconfiguration plainly
        return JSONResponse({"ok": False, "error": str(exc)[:400]}, status_code=500)


class _TokenAuthMiddleware:
    """Reject any /mcp request without a live access token, before it reaches
    the MCP app. The OAuth endpoints themselves stay open -- a client has to
    reach them before it has a token at all -- and so does /health."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].rstrip("/") != "/mcp":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"").decode()
        token_value = auth[7:] if auth.startswith("Bearer ") else ""
        if not oauth.validate_access_token(token_value):
            host = headers.get(b"host", b"").decode()
            issuer = PUBLIC_URL or f"https://{host}"
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"text/plain"),
                    (b"www-authenticate",
                     f'Bearer resource_metadata="{issuer}/.well-known/oauth-protected-resource"'.encode()),
                ],
            })
            await send({"type": "http.response.body", "body": b"Unauthorized"})
            return

        await self.app(scope, receive, send)


def _transport_security() -> TransportSecuritySettings:
    """Allowlist the hostnames this deployment actually answers to.

    The SDK's DNS-rebinding protection rejects any Host header it does not
    recognize, and it matches exactly -- no domain wildcards. Left at its
    default it trusts only localhost, which is why this passed every local
    test and then returned 421 to every real request.

    Vercel names the deployment in its own environment, so the allowlist is
    built from that rather than hardcoded: the production domain, this
    specific deployment, and any branch alias. If none of them are set we
    turn the check off rather than reject everything -- Vercel's edge already
    refuses unknown hosts before a request reaches this function, so the
    check is a second lock on the same door, never the only one.
    """
    candidates = [
        urlparse(PUBLIC_URL).netloc if PUBLIC_URL else "",
        os.environ.get("VERCEL_PROJECT_PRODUCTION_URL", ""),
        os.environ.get("VERCEL_URL", ""),
        os.environ.get("VERCEL_BRANCH_URL", ""),
    ]
    hosts = sorted({h for h in candidates if h})
    if not hosts:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts + ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*"],
        allowed_origins=[f"https://{h}" for h in hosts] + ["https://claude.ai"],
    )


# stateless_http: no per-session state, so any instance can serve any request.
# json_response: plain JSON replies rather than a held-open SSE stream, which
# a function with a wall-clock limit cannot keep alive anyway.
app = _TokenAuthMiddleware(
    mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=_transport_security(),
    )
)
