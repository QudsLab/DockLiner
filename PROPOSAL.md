# DockLiner - Development Plan

## 1. Project Overview

**DockLiner** is a lightweight, self-hosted deployment management system for personal Docker-based projects. It allows centralized management of multiple GitHub repositories, automated deployment via Docker Compose, and monitoring — all running natively on the host server alongside aaPanel.

**Core Goals**:

- Single GitHub PAT for all repositories.
- Clean, reproducible deployments with aggressive cleanup.
- Simple web dashboard for one-click deploy/restart/stop.
- SQLite-backed state management.
- High safety and minimal overhead.
- Full compatibility with existing aaPanel setup.

**Service Name**: `dockliner`

---

## 2. Technology Stack

- **Backend**: Python 3.11+ + FastAPI
- **ASGI Server**: Gunicorn + Uvicorn workers
- **Database**: SQLite (via SQLAlchemy + Alembic for migrations)
- **Git Operations**: GitPython
- **Docker Management**: Docker Python SDK (`docker` package)
- **Frontend**: HTMX + Tailwind CSS (lightweight, no heavy React)
- **Environment**: `.env` + python-dotenv
- **Deployment**: Systemd service (native host)
- **Logging**: Structured logging to `/data/logs/`

---

## 3. Directory Structure (Final)

```
/data/
├── dockliner/                  # Main application
│   ├── main.py
│   ├── app/
│   │   ├── __init__.py
│   │   ├── core/               # config, database, security
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
├── github-cache/               # Temporary clone area
├── cool-deploy.db              # Renamed to dockliner.db ?
└── logs/
```

---

## 4. Phase-wise Development Plan

### Phase 1: Foundation (Current Priority)

- [ ] Set up project structure and virtual environment
- [ ] Create `requirements.txt` and install dependencies
- [ ] Initialize SQLite database + SQLAlchemy models (Projects, Deployments)
- [ ] Implement Git clone/pull service using PAT
- [ ] Implement Docker service (build, up, down, logs, status)
- [ ] Create basic FastAPI routes (health check, list projects)
- [ ] Systemd service file (`dockliner.service`)

### Phase 2: Core Deployment Engine

- [ ] Full deployment pipeline:
  - Clone → Rsync (with --delete) → docker compose down → build & up
- [ ] Aggressive cleanup (temp files + docker prune)
- [ ] Environment variable management (`.env` per project)
- [ ] Deployment history logging
- [ ] Error handling and rollback strategy

### Phase 3: Web Dashboard

- [ ] Project list with status
- [ ] One-click Deploy / Restart / Stop / Logs
- [ ] Add / Edit project form
- [ ] Simple authentication (username/password + session)
- [ ] Responsive UI with Tailwind + HTMX

### Phase 4: Polish & Safety

- [ ] Validation (compose file exists, Docker running, etc.)
- [ ] Background task for deployments (Celery or FastAPI BackgroundTasks)
- [ ] Rate limiting and security headers
- [ ] Backup utility for `/data/`
- [ ] Logging and monitoring endpoints

### Phase 5: Advanced Features (Future)

- [ ] GitHub webhook support
- [ ] Portainer integration option
- [ ] Resource usage monitoring
- [ ] One-click templates
- [ ] Preview / staging environments

---

## 5. Security Considerations

- Run as non-root user (`dockliner` user in `docker` group)
- GitHub PAT with `repo` (read-only) scope
- Limited Docker socket access
- Input validation on all GitHub URLs and commands
- No exposed sensitive credentials in UI

---

## 6. Next Immediate Steps (Recommended)

1. Create non-root user `dockliner` and add to docker group
2. Set up project skeleton in `/data/dockliner/`
3. Implement core models and services
4. Create and enable systemd service
5. Build basic dashboard

---

## 7. Success Criteria

- Can successfully deploy a test project from GitHub in < 2 minutes
- Survives server reboot (auto-start via systemd)
- Clean directory structure with no junk files
- Easy to manage 5–10 personal projects
- Works smoothly with aaPanel Nginx reverse proxy

---

**Status**: Planning Complete  
**Next Action**: Start implementation of Phase 1

---

**Last Updated: June 2026**