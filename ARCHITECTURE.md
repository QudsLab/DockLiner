# Deployment Management System Architecture

## 1. Overview

This document describes a lightweight, unified deployment system for managing multiple personal projects (e.g., OpenS, Pairport, etc.) on a single server with aaPanel already installed.

**Goals**:

- Single GitHub Personal Access Token (PAT) to access any repository.
- Centralized management via SQLite database.
- Clean directory structure with aggressive cleanup (no junk files).
- Simple "hit action" deployment (manual trigger via web UI or GitHub).
- Docker-first (Dockerfile + Docker Compose support).
- Minimal overhead, works alongside aaPanel.
- High safety and reproducibility.

## 2. High-Level Components

```flow
[GitHub] <--(PAT Read)--> [Custom Manager / Portainer]
                          |
                          v
                   [SQLite DB]
                          |
                          v
                [Host Server + Docker]
                          |
                 /data/projects/{name}/
```

### Core Services

- **Manager/Dashboard**: Web UI or lightweight service (FastAPI/Python or Node.js).
- **Database**: SQLite (`/data/cool-deploy.db`).
- **Runtime**: Docker + Docker Compose.
- **Proxy**: aaPanel Nginx or Traefik (for the manager itself).

## 3. Directory Structure (Strictly Enforced)

```tree
/data/
├── projects/                  # All live applications (clean & persistent)
│   ├── opens/
│   │   ├── docker-compose.yml
│   │   ├── .env (gitignored)
│   │   └── app code...
│   ├── pairport/
│   └── ...
├── github-cache/              # Temporary clone area (cleaned after each deploy)
├── cool-deploy.db             # SQLite database
├── logs/                      # Deployment logs
└── manager/                   # Optional: dashboard source if custom
```

- Persistent data (DBs, uploads) uses Docker volumes mapped to `/data/projects/{name}/data/`.

## 4. Data Model (SQLite)

**Projects Table**:

- `id`
- `name` (unique)
- `github_repo_url`
- `branch` (default: main)
- `deploy_path` (/data/projects/{name})
- `compose_file` (default: docker-compose.yml)
- `status` (running/stopped/error)
- `last_deployed`
- `env_vars` (JSON)
- `labels` / tags

**Deployments Table** (history):

- `project_id`, `timestamp`, `status`, `logs`

## 5. Deployment Flow

1. User selects project in dashboard → "Deploy".
2. System:
   - Clones/pulls repo into temporary clean directory using GitHub PAT.
   - Rsyncs (with `--delete`) to `/data/projects/{name}/`.
   - Runs `docker compose down --rmi local --remove-orphans`.
   - Runs `docker compose up -d --build`.
   - Updates SQLite status + logs.
3. Aggressive cleanup:
   - `rm -rf` temporary files.
   - `docker system prune -f`.

## 6. Technologies

- **Backend**: Python + FastAPI (recommended) or Flask.
- **Git**: `PyGithub` or `gitpython` + PAT.
- **Docker**: Docker Python SDK or subprocess calls to `docker compose`.
- **Auth**: Simple username/password or GitHub OAuth for dashboard.
- **Alternative (No/Low Code)**: Portainer (Git stacks + PAT) as base.

## 7. Security & Safety

- Run manager as non-root user.
- GitHub PAT with minimal scopes (repo read only).
- Runner/Dashboard container has limited Docker socket access if needed.
- Backups of `/data/` and SQLite.
- Validation before deploy (check compose file exists).

## 8. Integration with aaPanel

- aaPanel handles traditional sites, domains, SSL.
- Manager runs on a different port (e.g., 8080).
- Use aaPanel reverse proxy to expose manager securely.
- Docker containers managed by the system appear in aaPanel Docker module / Portainer.

## 9. Future Extensions

- Webhook support from GitHub.
- Preview environments.
- One-click templates.
- Monitoring (Portainer or Prometheus).

--- 

**Next Steps**:

1. Decide: Pure custom (FastAPI) vs Portainer-first.
2. Install Portainer or bootstrap the Python dashboard.
3. Create the SQLite schema and first project entries.

This architecture gives you a clean, maintainable, and safe unified system with minimal per-project hassle.
