<div align="center">

<img src="app/static/img/logo.svg" width="92%" alt="DockLiner Banner" />

</div>

<br>
<br>

A lightweight, self-hosted deployment management system for personal Docker-based projects. DockLiner provides centralized management of multiple GitHub repositories, automated deployment via Docker Compose, and monitoring all running natively on the host server alongside aaPanel.

## Core Goals

- **Single GitHub PAT** - One Personal Access Token to access all repositories.
- **Clean, reproducible deployments** - Aggressive cleanup with no junk files left behind.
- **Simple web dashboard** - One-click deploy, restart, stop, and view logs.
- **SQLite-backed state management** - Lightweight, no external database required.
- **High safety & minimal overhead** - Runs as non-root user with limited Docker socket access.
- **Full aaPanel compatibility** - Works alongside existing aaPanel setup with reverse proxy support.

## Technology Stack

| Component | Technology |
|---|---|
| Backend | Python 3.11+ / FastAPI |
| ASGI Server | Gunicorn + Uvicorn workers |
| Database | SQLite (via SQLAlchemy + Alembic) |
| Git Operations | GitPython |
| Docker Management | Docker Python SDK |
| Frontend | HTMX + Tailwind CSS |
| Environment | `.env` + python-dotenv |
| Deployment | Systemd service (native host) |
| Logging | Structured logging to `/data/logs/` |

## Directory Structure

```
/data/
├── dockliner/                  # Main application
│   ├── main.py
│   ├── app/
│   │   ├── core/               # Config, database, security
│   │   ├── models/             # SQLAlchemy models
│   │   ├── schemas/            # Pydantic models
│   │   ├── routers/            # API endpoints
│   │   ├── services/           # Business logic (git, docker, deploy)
│   │   ├── templates/          # Jinja2 + HTMX templates
│   │   └── utils/
│   ├── alembic/                # Database migrations
│   ├── static/                 # CSS, JS
│   ├── logs/
│   ├── .env
│   ├── requirements.txt
│   └── gunicorn.conf.py
├── projects/                   # Live project directories
├── github-cache/               # Temporary clone area (cleaned after deploy)
├── dockliner.db                # SQLite database
└── logs/                       # Deployment logs
```

## Data Model

### Projects Table

| Field | Description |
|---|---|
| `id` | Primary key |
| `name` | Unique project name |
| `github_repo_url` | GitHub repository URL |
| `branch` | Git branch (default: `main`) |
| `deploy_path` | Deployment path (`/data/projects/{name}`) |
| `compose_file` | Compose file name (default: `docker-compose.yml`) |
| `status` | Current status (`running` / `stopped` / `error`) |
| `last_deployed` | Timestamp of last deployment |
| `env_vars` | Environment variables (JSON) |
| `labels` | Tags / labels |

### Deployments Table (History)

| Field | Description |
|---|---|
| `project_id` | Foreign key to Projects |
| `timestamp` | Deployment time |
| `status` | Deployment result |
| `logs` | Deployment log output |

## Deployment Flow

1. User selects a project in the dashboard → clicks **Deploy**.
2. System clones/pulls the repo into a temporary clean directory using the GitHub PAT.
3. Rsyncs (with `--delete`) to `/data/projects/{name}/`.
4. Runs `docker compose down --rmi local --remove-orphans`.
5. Runs `docker compose up -d --build`.
6. Updates SQLite status and logs.
7. **Aggressive cleanup**:
   - `rm -rf` temporary clone files.
   - `docker system prune -f`.

## Security

- Runs as non-root user (`dockliner`) in the `docker` group.
- GitHub PAT with minimal scope (`repo` read-only).
- Limited Docker socket access.
- Input validation on all GitHub URLs and commands.
- No exposed sensitive credentials in the UI.

## aaPanel Integration

- aaPanel handles traditional sites, domains, and SSL.
- DockLiner runs on a separate port (e.g., `8080`).
- Use aaPanel reverse proxy to expose the dashboard securely.
- Docker containers managed by DockLiner appear in aaPanel Docker module.

## Development Phases

### Phase 1 - Foundation
- Project structure, dependencies, SQLite models, Git/Docker services, basic API routes, systemd service.

### Phase 2 - Core Deployment Engine
- Full deployment pipeline, aggressive cleanup, `.env` per project, deployment history, error handling & rollback.

### Phase 3 - Web Dashboard
- Project list with status, one-click actions, add/edit forms, simple authentication, responsive UI.

### Phase 4 - Polish & Safety
- Validation, background tasks, rate limiting, security headers, backup utility, monitoring endpoints.

### Phase 5 - Advanced Features (Future)
- GitHub webhook support, Portainer integration, resource monitoring, one-click templates, preview/staging environments.

## Quick Start

1. Create non-root user `dockliner` and add to the `docker` group.
2. Clone this repository and set up the project skeleton in `/data/dockliner/`.
3. Copy `.env.example` to `.env` and configure your GitHub PAT and settings.
4. Install dependencies: `pip install -r requirements.txt`.
5. Run the application: `python main.py`.
6. Create and enable the systemd service for auto-start on reboot.

## Success Criteria

- Deploy a test project from GitHub in under 2 minutes.
- Survives server reboot (auto-start via systemd).
- Clean directory structure with no junk files.
- Easy to manage 5–10 personal projects.
- Works smoothly with aaPanel Nginx reverse proxy.

---

**Status**: Planning Complete  
**Last Updated**: June 2026
