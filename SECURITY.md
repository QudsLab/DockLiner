# DockLiner Security Analysis

## Authentication
- BLAKE3-512 password hashes stored in `app/core/config.py` `USERS` JSON array.
- Root user `root` with password `qwer.1234` has a hardcoded hash; non-resettable.
- Session cookies (`dockliner_user`, `dockliner_login`) with `httponly` and `samesite="lax"`.
- Rate limiting: 5 login attempts per minute per IP.

## Authorization
- Single-user model. No roles, no multi-tenant isolation.
- All authenticated users have full access to all projects, tokens, Docker commands, and audit logs.

## Input Validation
- FastAPI/Pydantic validates request schemas. No SQL injection via ORM.
- Project names must be unique (DB constraint).
- GitHub repo URLs are stored as plain strings; no URL validation beyond `nullable=True`.
- `RateLimitService` caps deploy attempts: 3 per minute per project per IP.

## Docker Security
- Docker daemon runs on localhost only. No remote Docker host support.
- `docker scout quickview` may expose registry login requirements in stderr (see below).
- Container operations (stop, remove, image remove) are unrestricted once authenticated.
- `docker system prune -f` runs automatically after every deploy — irreversible.

## Secrets Management
- GitHub tokens stored in SQLite (`access_tokens.token`) as plaintext. No encryption at rest.
- `.env` files written to disk in `projects/<name>/` directories.
- `SECRET_KEY` defaults to `"change-me"` if not set via env.

## Known Issues
1. **Docker Scout login leak**: `docker scout quickview` stderr may contain marketing text about Docker ID/login if not authenticated. This is returned in the security summary `output` field. Not a secret leak, but noisy.
2. **Plaintext tokens**: `access_tokens.token` is stored in plaintext in SQLite. Anyone with DB file access can read tokens.
3. **No HTTPS enforcement**: Cookies are `httponly` but not `secure`. Suitable for localhost only.
4. **Docker prune on every deploy**: `DeployService.deploy_project()` calls `DockerService.system_prune()` unconditionally. This removes unused images, networks, and volumes system-wide.

## Recommendations
- Run behind HTTPS reverse proxy (nginx/caddy) in production.
- Encrypt `access_tokens.token` with AES-256-GCM using `SECRET_KEY` as key.
- Remove automatic `docker system prune` or make it opt-in per project.
- Add project-level ownership if multi-user is ever needed.
- Sanitize `docker scout` output before returning in API responses.
