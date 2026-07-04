# Docker Project Setup in DockLiner

The **Project Setup** page (`/projects/add` or `/projects/<id>/setup`) is where you tell DockLiner how to build and run your project with Docker. This guide explains every field, mode, and option available on that page.

---

## 1. Project basics

At the top of the page you define the high-level project metadata.

| Field | Description |
|-------|-------------|
| **Source** | Shows where the code came from: GitHub clone, local directory, or an existing download. Read-only. |
| **Detected files** | Colored chips indicate whether `compose.yml` / `Dockerfile` / `.env` / `.env.example` were found in the source. |
| **Project name** | Required. Used as the container name prefix and project identifier. |
| **Port** | Optional host port. If left blank, DockLiner auto-assigns a port. |
| **Template** | Pick a preset to pre-fill the deployment mode: Node.js, Python, Static HTML, or PHP Apache. |

---

## 2. Deployment modes

Choose how DockLiner should run the project. Three modes are supported.

### 2.1 Compose (recommended)

Uses a `docker-compose.yml` file.

- **Form view** — visually add services, volumes, networks, ports, environment variables, and volume mounts.
- **Raw view** — edit the generated YAML directly.
- **Actions** — Load example, Clear.

Per service you can configure:

- `image` or `build` context
- `container_name`
- `ports` (`HOST:CONTAINER`)
- `environment` variables (`KEY=VALUE`)
- `volumes` (`HOST:CONTAINER[:ro]`)
- `networks`
- `restart` policy

Top-level volumes and networks are also editable in their own sections.

### 2.2 Dockerfile

Uses a single `Dockerfile`.

- **Decorated view** — syntax-highlighted read-only preview.
- **Raw view** — full Dockerfile editing.
- **Actions** — Load example, Clear.

DockLiner builds the image and runs a container from it.

### 2.3 Direct command

For simple one-off containers.

| Field | Description |
|-------|-------------|
| **Image / Build context** | Image name or tag to run (or build). |
| **Container name** | Name given to the running container. |
| **Host port** | Port exposed on the host. |
| **Container port** | Port the application listens to inside the container. |
| **Build context `.`** | Toggle to add a `docker build` step before `docker run`. |

A live preview of the generated `docker build` + `docker run` command is shown.

---

## 3. Environment variables

The `.env` editor lets you manage environment variables passed to the container.

- If `.env` was detected in the source, it is loaded automatically.
- If `.env.example` exists, a **Copy from .env.example** button fills the editor with the example values.
- You can edit or clear the content before creating the project.

---

## 4. Advanced runtime options

Expand the **Advanced runtime options** section to fine-tune the build/run.

| Option | Description |
|--------|-------------|
| **Build args** | Extra `docker build` flags, one per line (e.g. `--no-cache`, `--pull`). |
| **Run options** | Extra `docker run` / `docker-compose up` flags, one per line (e.g. `--detach`, `--remove-orphans`). |
| **Pull latest base images on build** | Adds `--pull` so base images are refreshed on each build. |

---

## 5. Review and create

The review card summarizes:

- Project name
- Source type
- Selected command mode
- Port (auto or explicit)

Click **Create Project** to save the configuration. DockLiner stores it and, depending on the mode, runs `docker-compose up`, `docker build` + `docker run`, or the direct command.

Use the **Back** button to return to the previous step without saving.

---

## 6. What DockLiner sends to the backend

When you press **Create Project**, the frontend posts a JSON payload to `POST /api/projects` containing:

```json
{
  "name": "my-app",
  "port": 25600,
  "env_content": "...",
  "example_env_content": "...",
  "compose_file": "docker-compose.yml",
  "compose_content": "version: '3.8'\n...",
  "dockerfile_content": "...",
  "direct_command": "...",
  "command_mode": "compose",
  "deploy_method": "compose",
  "source_type": "github",
  "source_path": "...",
  "raw_mode": false,
  "github_repo_url": "..."
}
```

The backend uses this payload to write the generated files, create the project record, and trigger the deployment.
