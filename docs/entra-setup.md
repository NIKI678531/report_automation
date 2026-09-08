# Connecting the API to Microsoft Entra ID

`AUTH_MODE=ENTRA` is the only supported production setting. This is what the directory has to
provide, what the API does with it, and how to prove it works before anyone depends on it.

`AUTH_MODE=LOCAL` — the default — reads the caller's identity from `X-User-Role`, `X-User-ID` and
`X-Product-Scope` request headers and believes them. It exists so a developer can work without a
tenant. It is not a weaker form of security; it is none, and the application refuses to start in
that mode with any other production setting in place.

## What the API needs

Three things, and it fails closed without any of them:

| Need | Where it comes from | Consequence if absent |
| --- | --- | --- |
| A signature it can verify | The tenant's JWKS endpoint, fetched over https and cached | `AUTH_PROVIDER_UNREACHABLE`, 503 |
| An **audience** to pin | `ENTRA_AUDIENCE` = this API's Application ID URI or client id | `TOKEN_AUDIENCE_REJECTED`, 401 |
| A **role** and a **product scope** per caller | Claims in the access token | `ROLE_NOT_ASSIGNED` / `PRODUCT_SCOPE_NOT_ASSIGNED`, 403 |

Roles are `VIEWER < EDITOR < REVIEWER < ADMIN`. Product scope is the set of `product_code`s that
caller may see, or `*`. They answer different questions on purpose: the role says what kind of act
is allowed, the scope says which funds it may touch. A report outside the caller's scope is
reported as absent rather than refused, because a 403 would confirm it exists.

## 1. Register the API

In **Entra admin centre → App registrations → New registration**, register the API itself (not the
browser client). Then under **Expose an API**, set the Application ID URI — `api://commentary` is
the conventional form. That URI is the value of `ENTRA_AUDIENCE`; a token minted for any other
audience is a token for another service and is rejected.

Record the **Directory (tenant) ID**. Issuer and JWKS URLs are derived from it:

```
https://login.microsoftonline.com/<tenant>/v2.0                        # ENTRA_ISSUER
https://login.microsoftonline.com/<tenant>/discovery/v2.0/keys         # ENTRA_JWKS_URL
```

Set them explicitly only if your tenant does not use those standard forms.

## 2. Declare the four app roles

**App roles → Create app role**, once per role, with `allowedMemberTypes: ["User"]`. The **value**
is what lands in the token and must match exactly, in upper case:

```json
[
  { "displayName": "Viewer",        "value": "VIEWER",   "description": "Read reports and artifacts.",           "allowedMemberTypes": ["User"], "isEnabled": true },
  { "displayName": "Editor",        "value": "EDITOR",   "description": "Edit documents, upload data, render.",  "allowedMemberTypes": ["User"], "isEnabled": true },
  { "displayName": "Reviewer",      "value": "REVIEWER", "description": "Everything an editor may do, plus finalize.", "allowedMemberTypes": ["User"], "isEnabled": true },
  { "displayName": "Administrator", "value": "ADMIN",    "description": "Product catalog, industry master and mapping profiles.", "allowedMemberTypes": ["User"], "isEnabled": true }
]
```

Assign them under **Enterprise applications → this app → Users and groups**. Entra emits them in
the `roles` claim, which is the default `ENTRA_ROLE_CLAIM`. If several roles are assigned to one
person, the most privileged wins.

## 3. Decide how product scope is carried

Entra has no built-in notion of "which funds may this person see", so pick one of three and
configure the API to match. The API accepts the claim as a JSON array, a space-delimited string or
a comma-separated string, so any of these shapes works.

**a. A custom claim (recommended).** Emit a `product_scope` claim from a directory extension
attribute or a claims-mapping policy, containing the product codes (`3033 3037`) or `*`. Leave
`ENTRA_PRODUCT_SCOPE_CLAIM=product_scope`.

**b. Reuse group membership.** Point `ENTRA_PRODUCT_SCOPE_CLAIM` at `groups` and name the groups
after product codes. Workable, but group claims are truncated above ~200 memberships, and a
truncated claim silently narrows what someone can see.

**c. Do not model scope at all.** Set `ENTRA_PRODUCT_SCOPE_CLAIM=` (empty). Every authenticated
caller then sees every product. This is an explicit opt-out because silence is not treated as
consent: a token with a *configured* scope claim that carries no value is refused, not widened.

## 4. Configure the deployment

In `.env` beside `compose.yaml` (or the platform's secret store):

```bash
AUTH_MODE=ENTRA
ENTRA_TENANT_ID=<directory tenant id>
ENTRA_AUDIENCE=api://commentary
ENTRA_ROLE_CLAIM=roles
ENTRA_PRODUCT_SCOPE_CLAIM=product_scope

# 32+ generated characters, identical in api and worker:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
DOWNLOAD_SECRET=...
```

Install the extra that carries the signature verification:

```bash
pip install -e "./backend[entra]"
```

It is a separate extra because `LOCAL` never verifies a signature. Its absence fails startup rather
than the first authenticated request — a service that reports healthy and then 500s on every login
is worse than one that never came up.

Defaults worth leaving alone: `ENTRA_ALLOWED_ALGORITHMS=RS256` (the startup guard refuses any
symmetric `HS*` algorithm and `none` — with `HS*` allowed, a public key from the JWKS doubles as a
signing key and anyone can mint an admin token), `ENTRA_JWKS_CACHE_SECONDS=3600`, and
`ENTRA_LEEWAY_SECONDS=60` for clock skew.

## 5. Prove it before anyone depends on it

```powershell
$env:AUTH_MODE = "ENTRA"
.\.venv\Scripts\python scripts/check_deployment.py --token "$ACCESS_TOKEN"
```

The preflight runs the same checks that would refuse startup, then the ones the application only
reaches at first use: the database is connectable and at head, the JWKS endpoint answers, and — with
`--token` — a real access token resolves to a real subject, role and product scope. The token is
never logged. A non-zero exit means the environment must not serve traffic.

Get a token to test with from the browser client, or:

```bash
az account get-access-token --resource api://commentary --query accessToken -o tsv
```

## Troubleshooting

Every failure returns the same envelope, so the `error_code` names the cause exactly:

| `error_code` | Status | What actually happened |
| --- | --- | --- |
| `AUTHENTICATION_REQUIRED` | 401 | No `Authorization: Bearer <token>` header. In `ENTRA` mode the `X-User-*` headers are ignored entirely. |
| `AUTH_BACKEND_UNAVAILABLE` | 500 | PyJWT is not installed. `pip install -e "./backend[entra]"`. |
| `AUTH_NOT_CONFIGURED` | 500 | No audience, issuer or JWKS URL is configured, or the JWKS URL is not `https://`. |
| `AUTH_PROVIDER_UNREACHABLE` | 503 | The tenant's key endpoint did not answer, or answered with something that was not a key set. Check outbound access to `login.microsoftonline.com`. |
| `TOKEN_MALFORMED` | 401 | Not a JWT, or its header is unreadable. |
| `TOKEN_ALGORITHM_REJECTED` | 401 | Signed with an algorithm outside `ENTRA_ALLOWED_ALGORITHMS` — including `none`. |
| `TOKEN_KEY_UNKNOWN` | 401 | Signed with a `kid` the tenant does not publish. Usually the wrong tenant. |
| `TOKEN_EXPIRED` | 401 | Past `exp` plus the leeway. If it happens constantly, check clock skew on the host. |
| `TOKEN_AUDIENCE_REJECTED` | 401 | A token for a different API. The client requested the wrong resource/scope. |
| `TOKEN_ISSUER_REJECTED` | 401 | Right shape, wrong tenant — or a v1.0 token where a v2.0 issuer is pinned. |
| `TOKEN_INVALID` | 401 | The signature does not match the payload. |
| `TOKEN_SUBJECT_MISSING` | 401 | No `oid` or `sub`. Nothing could be attributed to a caller in the audit trail. |
| `ROLE_NOT_ASSIGNED` | 403 | Authenticated, but no app role assigned — or `ENTRA_ROLE_CLAIM` names the wrong claim. |
| `PRODUCT_SCOPE_NOT_ASSIGNED` | 403 | Authenticated with a role, but no product scope claim. See step 3. |

The audit trail records the token's `oid`, not `sub`: `oid` is the immutable per-tenant object id,
while `sub` is pairwise and rotates per application, so only `oid` still resolves to a person months
after the fact.
