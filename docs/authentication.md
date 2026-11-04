# Multi-user authentication

SchemaPilot supports provider-agnostic OpenID Connect (OIDC) sign-in using the Authorization Code flow. Authentication is off by default. It becomes active only when `SCHEMAPILOT_AUTH_REQUIRED=true` and all OIDC client, callback, and session-secret settings are present. Incomplete required configuration fails startup instead of silently opening the app.

## Identity provider setup

Register SchemaPilot as a confidential OIDC web client with:

- A tenant- or organization-scoped issuer and discovery metadata URL.
- The callback URI `https://<your-host>/api/v1/auth/callback` (use the exact host and scheme configured locally).
- Authorization Code flow and the `openid`, `profile`, and `email` scopes.
- Application assignment restricted to the organization’s intended users.
- Role values in the configured role claim and membership group values in the configured group claim.

Do not use a public issuer that permits arbitrary accounts unless the provider itself restricts app assignment. SchemaPilot does not provide local passwords, invitations, or account recovery; manage users and group membership in the identity provider.

### Microsoft Entra ID (selected for this workspace)

1. In Microsoft Entra admin center, create an App Registration for SchemaPilot as a **Web** application. Use single-tenant access for the organization.
2. For local development, register `http://127.0.0.1:8000/api/v1/auth/callback` as a Web redirect URI. The frontend is `http://127.0.0.1:5175`; it signs in through the backend callback.
3. Use the tenant-specific discovery URL `https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration` as `SCHEMAPILOT_OIDC_METADATA_URL`.
4. Create app roles with exact values `admin`, `engineer`, `approver`, and `viewer`, assign them to the intended users or groups, and keep app assignment restricted to SchemaPilot users.
5. Configure the ID token to include the app roles claim (`roles`) and a `groups` claim limited to groups assigned to this application. Assign the team security group to the enterprise application, then set `SCHEMAPILOT_AUTH_TEAM_GROUPS` to that group’s object ID. A missing/overage group claim fails closed for shared access; confirm the group appears in the ID token before inviting users.
6. Copy the Application (client) ID into `SCHEMAPILOT_OIDC_CLIENT_ID`. Create a client secret in Entra and enter it directly into local `backend/.env`; never send it in chat. Generate an independent session secret of at least 32 characters.
7. In the local `.env`, set `SCHEMAPILOT_AUTH_REQUIRED=true`, the tenant-specific discovery URL, the local callback and frontend URLs, and `SCHEMAPILOT_AUTH_COOKIE_SECURE=false` for HTTP localhost only. Restart Uvicorn and confirm `/api/v1/health` reports `authentication_available=true` before sign-in testing.

For deployment, use the deployed HTTPS origin in both redirect and frontend URLs, set the secure cookie flag to true, and store the client secret and session secret in the deployment secret store.

Configure these values in `backend/.env` or the deployment secret store:

```dotenv
SCHEMAPILOT_AUTH_REQUIRED=true
SCHEMAPILOT_OIDC_METADATA_URL=https://<issuer>/.well-known/openid-configuration
SCHEMAPILOT_OIDC_CLIENT_ID=<client-id>
SCHEMAPILOT_OIDC_CLIENT_SECRET=<secret-store-value>
SCHEMAPILOT_OIDC_REDIRECT_URI=https://<your-host>/api/v1/auth/callback
SCHEMAPILOT_AUTH_FRONTEND_URL=https://<your-host>
SCHEMAPILOT_AUTH_SESSION_SECRET=<independent-random-secret-at-least-32-characters>
SCHEMAPILOT_AUTH_COOKIE_SECURE=true
SCHEMAPILOT_AUTH_ROLE_CLAIM=roles
SCHEMAPILOT_AUTH_GROUP_CLAIM=groups
SCHEMAPILOT_AUTH_ADMIN_ROLES=admin
SCHEMAPILOT_AUTH_ENGINEER_ROLES=engineer
SCHEMAPILOT_AUTH_APPROVER_ROLES=approver
SCHEMAPILOT_AUTH_VIEWER_ROLES=viewer
SCHEMAPILOT_AUTH_TEAM_GROUPS=schemapilot-team
```

Role and group claims may use dotted paths, such as `realm_access.roles`. Values are case-insensitive. An Admin also has Engineer and Approver capabilities. Team access requires membership in a configured team group or the Admin role. A user without team-group membership can still use their private workspace.

For local HTTP development only, use a local callback URI and set `SCHEMAPILOT_AUTH_COOKIE_SECURE=false`. Never disable Secure cookies on a deployed HTTPS site. Generate a new session secret separately from the provider secret; keep both out of source control and logs.

## Access model

| Role | Read sources and history | Propose, generate, validate, save | Record approval |
| --- | --- | --- | --- |
| Viewer | Yes | No | No |
| Engineer | Yes | Yes | No |
| Approver | Yes | No | Yes, for another user's eligible workflow |
| Admin | Yes | Yes | Yes, for another user's eligible workflow |

Engineers and Admins can save private workflows, which are visible only to their OIDC subject. Shared workflows are visible to members of the configured team group and Admins. Legacy workflows are treated as shared; apply the Alembic migration before enabling OIDC against an existing app database. Admins do not gain access to private workflows through this application layer.

Approval records remain separate from execution. An owner cannot approve their own workflow. Approval is allowed only after the existing report, evidence, and rollback checks pass. No target apply endpoint exists; target execution and migrations-on-startup must remain disabled.

## Session and API protections

- Authlib validates the OIDC response and authorization state. Access and refresh tokens are not stored in the browser session.
- The app stores a minimal signed session in an HTTP-only, SameSite=Lax cookie with an eight-hour lifetime. Production cookies use Secure.
- Mutating API calls require the per-session CSRF token in `X-CSRF-Token`.
- Health and authentication routes remain public; source, plan, artifact, sandbox, safety, and workflow APIs require a signed-in session. API documentation routes are disabled when OIDC is active.
- Application membership and roles come from OIDC role/group claims; client-supplied names or roles are ignored.

When OIDC is disabled, `/api/v1/auth/me` reports `enabled=false` and
`authenticated=false`; the local-console `can_access_team_workspace` capability
does not represent a verified identity or a team membership claim. Approval
recording remains unavailable in this mode. UI confirmation is not human
approval, and an approval record is not target execution.

## Current security boundary

- Target execution is not implemented: there is no apply route or background
  target executor. The target preflight always rejects, even if a caller
  constructs settings or evidence that would otherwise pass its checks.
- Startup migrations are guarded off. App database Alembic upgrades require an
  explicit operator opt-in through the migration command; do not set that opt-in
  for normal application startup.
- Sandbox execution validates a dedicated server-configured sandbox URL and
  rejects URLs matching the app, demo, or configured target database. The
  frontend cannot supply a database URL to select an execution destination.
- Approval checks require an authenticated Approver, a different workflow owner,
  explicit confirmation, eligible persisted evidence, and a valid rollback and
  checkpoint report. Approval is persisted as evidence only; it does not apply
  SQL. Authentication remains disabled in the current local configuration, so
  a verified human approval cannot presently be recorded.
- Planning and artifact creation produce review material; generated SQL is
  constrained by the structured operation model and sandbox SQL parser before
  sandbox execution. LLM output is treated as untrusted input and cannot execute
  SQL directly.
- Error responses intentionally avoid reflecting provider response bodies and
  database URLs. There is no configured production log pipeline or deployment
  profile in this repository; operational log access and secret injection must
  be designed before deployment.

These controls are code-level safeguards, not a production security
certification. Authentication, live role/group claims, deployment TLS, secret
rotation, and production logging controls remain unverified or unavailable.

## Database migration

The new owner/visibility columns are applied only through Alembic; application startup never migrates the database. Back up the application metadata database and verify `SCHEMAPILOT_APP_DATABASE_URL` before running:

```powershell
Set-Location C:\Users\suryabhansingh\Downloads\SchemaPilot\backend
$env:SCHEMAPILOT_ALLOW_APP_MIGRATIONS = 'true'
.\.venv\Scripts\python.exe -m alembic upgrade head
Remove-Item Env:\SCHEMAPILOT_ALLOW_APP_MIGRATIONS
```

The migration adds nullable owner identity and a `shared` visibility default so existing workflow rows remain readable. It does not touch source, demo, sandbox, or target databases.
