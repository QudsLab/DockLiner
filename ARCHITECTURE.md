# DockLiner System Architecture

## 1. Overview

DockLiner is a lightweight, self-hosted web dashboard for managing Docker-based projects on a single server. It sits alongside aaPanel and provides a unified UI for cloning GitHub repos, editing files, building images and deploying containers.

**Goals**
- Manage many projects from one dashboard.
- One GitHub Personal Access Token (PAT) for all repo access.
- SQLite database for project state, deployments, logs and settings.
- Web-based file editor with project-level file tree.
- One-click deploy / build / start / stop / restart actions.
- Minimal overhead and safe path traversal guards.

## 2. High-Level Components

```flow
[Browser]
   |
   v
[DockLiner Web UI]  (Jinja2 templates + JS)
   |
   v
[FastAPI Python backend]  (app/main.py + app/routers/*)
   |
   +--> [SQLite DB]        (projects, deployments, logs, tokens)
   +--> [Docker Engine]    (build, run, compose up/down)
   +--> [Project folders]  (projects/{name}/)
   +--> [GitHub API]       (clone/download via PAT)
```

### Core Services

- **Web UI**: server-rendered HTML pages (`app/templates/*.html`) with vanilla JavaScript for interactivity.
- **Backend**: FastAPI application created by `app/main.py` and mounted routers in `app/routers/`.
- **Database**: SQLAlchemy models + SQLite.
- **File store**: project files live on disk under each project's `deploy_path`.
- **Runtime**: Docker + `docker compose` invoked via subprocess.

## 3. Directory Layout

```tree
DockLiner/
├── main.py                      # Uvicorn entry point
├── ARCHITECTURE.md              # This file
├── app/
│   ├── main.py                  # FastAPI factory, middleware, routers
│   ├── core/                    # config, db, auth, utils
│   ├── models/                  # SQLAlchemy models
│   ├── routers/
│   │   ├── api.py               # REST API (projects, files, docker, logs, ...)
│   │   └── pages.py             # HTML page routes
│   ├── schemas/                 # Pydantic request/response models
│   ├── services/                # business logic (deploy, docker, logs, ...)
│   ├── static/                  # CSS, JS, vendor libraries
│   └── templates/               # Jinja2 pages
│       ├── base.html            # Common layout (nav, theme)
│       ├── dashboard.html       # Global system dashboard
│       ├── projects.html        # Projects list
│       ├── project_detail.html  # Project manage page (actions + popups)
│       ├── project_editor.html  # Full code editor (file tree + CodeMirror)
│       ├── downloads.html       # GitHub download manager
│       ├── settings.html        # System settings
│       ├── logs.html            # Runtime log view
│       └── system_logs.html     # System-wide logs
├── downloads/                   # Downloaded repo archives
├── github-cache/                # Temporary clone/extraction area
├── projects/                    # Live project folders (created per project)
└── data/
    └── dockliner.db             # SQLite database
```

## 4. Data Model (SQLite)

**Project**
- `id`, `name` (unique)
- `github_repo_url`, `branch`
- `deploy_path` (e.g. `projects/{name}`)
- `compose_file`, `command_mode`
- `port`, `status`
- `compose_content`, `dockerfile_content`, `env_content`
- `quick_deploy_commands` (JSON list)
- `labels`, `last_deployed`, `created_at`

**Deployment** (history)
- `id`, `project_id`
- `timestamp`, `status`, `logs`

**AccessToken**
- GitHub PAT storage.

**AuditLog / SystemLog / Notification / ErrorLog**
- Activity and error tracking.

## 5. Page Flow

1. **Projects list** (`/projects`) shows all registered and orphan project folders.
2. **Project manage page** (`/projects/{pid}`) gives action cards for Deploy, Build, Run/Start, Restart, Stop, Edit Files, Deploy Logs and Runtime Logs.
3. **File editor** (`/projects/{pid}/editor`) is a full-screen CodeMirror editor with a file tree, context menu (New / Rename / Delete / Cut / Copy / Paste), and editor toolbar (Undo, Redo, Cut, Copy, Paste, Select All, Select Line).
4. **Downloads** (`/downloads`) tracks downloaded repositories that can be promoted to projects.
5. **Settings** (`/settings`) configures GitHub tokens, Docker path and system preferences.

## 6. API Router Highlights

- `POST /api/login` / `POST /api/logout` — session cookie auth.
- `GET|POST|PATCH|DELETE /api/projects/{pid}` — project CRUD.
- `POST /api/projects/{pid}/build|deploy|run|start|restart|stop` — container lifecycle.
- `GET /api/projects/{pid}/files` — list files.
- `POST /api/projects/{pid}/files/move` — move/rename files (must be defined before generic `/{path}` routes).
- `GET|PUT|POST|DELETE /api/projects/{pid}/files/{path}` — read/write/create/delete files.
- `GET /api/projects/{pid}/deploy-logs` / `GET /api/projects/{pid}/logs` — logs.
- `GET /api/docker/...` — Docker containers, images, networks, volumes.
- `GET|POST /api/github/...` — GitHub integration (users, repos, releases, downloads).

## 7. Deployment Flow

1. User clicks **Quick Deploy** on the manage page.
2. Backend syncs source from GitHub/download cache to the project folder.
3. Writes `.env` from stored `env_content`.
4. Runs `docker compose -f <compose_file> build` and `up -d --build`.
5. Records a Deployment entry with status and output.
6. Refreshes project status and port mapping.

## 8. Technologies

- **Backend**: Python 3.11, FastAPI, Uvicorn, SQLAlchemy, Pydantic.
- **Frontend**: Jinja2, vanilla JavaScript, CSS custom properties, Material Symbols, CodeMirror 5.
- **Git**: `gitpython` + GitHub PAT for clones/downloads.
- **Docker**: subprocess calls to `docker compose` and Docker Python SDK where convenient.
- **Auth**: session-based cookie auth with a single root user (settings root password).

## 9. Security & Safety

- Session cookie auth via `require_auth` dependency.
- All file paths are resolved and checked with `Path.relative_to` to prevent traversal.
- GitHub PAT stored in settings, minimal scopes.
- Backups and cleanup utilities available in settings/cleanup pages.
- Non-root execution recommended.

## 10. Integration with aaPanel

- DockLiner runs on its own port (default 8080).
- aaPanel reverse proxy can expose it on a domain with SSL.
- Docker containers and persistent volumes are visible in aaPanel Docker module / Portainer.

## 11. Future Extensions

- Webhook-triggered auto-deploy.
- Preview environments per branch.
- One-click project templates.
- Monitoring dashboards (metrics/health) and alerting.
