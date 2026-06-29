"""Project templates — scaffold before the agent runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass
class ProjectTemplate:
    id: str
    label: str
    description: str
    stack: str

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "description": self.description, "stack": self.stack}


TEMPLATES: Dict[str, ProjectTemplate] = {
    "greenfield": ProjectTemplate("greenfield", "Greenfield", "Empty workdir — agent scaffolds from scratch", "any"),
    "cli": ProjectTemplate("cli", "Python CLI", "Typer CLI with tests and README", "python"),
    "python-api": ProjectTemplate("python-api", "Python API", "FastAPI service with pytest", "python"),
    "nextjs": ProjectTemplate("nextjs", "Next.js SaaS", "App router starter with npm test", "node"),
    "stripe-saas": ProjectTemplate(
        "stripe-saas",
        "Stripe SaaS",
        "BuilderShip SDK — Stripe Checkout + webhooks scaffold",
        "stripe",
    ),
    "qdrant-rag": ProjectTemplate(
        "qdrant-rag",
        "Qdrant RAG",
        "BuilderShip SDK — Qdrant vector store + ingestion stub",
        "qdrant",
    ),
    "motherduck-analytics": ProjectTemplate(
        "motherduck-analytics",
        "MotherDuck analytics",
        "BuilderShip SDK — DuckDB/MotherDuck analytics pipeline stub",
        "motherduck",
    ),
}


def list_templates() -> List[dict]:
    return [t.to_dict() for t in TEMPLATES.values()]


def _write_vercel_python_entrypoint(workdir: Path, app_import: str) -> None:
    api_dir = workdir / "api"
    api_dir.mkdir(exist_ok=True)
    (api_dir / "index.py").write_text(
        f'"""Vercel production entrypoint."""\n\nfrom {app_import} import app\n\n__all__ = ["app"]\n',
        encoding="utf-8",
    )
    (workdir / "vercel.json").write_text(
        '{\n'
        '  "$schema": "https://openapi.vercel.sh/vercel.json",\n'
        '  "rewrites": [{"source": "/(.*)", "destination": "/api/index"}]\n'
        '}\n',
        encoding="utf-8",
    )


def apply_template(
    workdir: Path, template_id: str, idea: str = "", preserve_existing: bool = False
) -> str:
    """Seed workdir files. Returns agent hint block.

    When ``preserve_existing`` is True (Creation is pointed at a directory that
    already contains a codebase), scaffolding templates are skipped entirely so
    Creation never overwrites the user's files — the agent works in place instead.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    tid = template_id if template_id in TEMPLATES else "greenfield"
    if tid == "greenfield":
        return "## Template\nGreenfield — scaffold full project structure."
    if preserve_existing:
        return (
            f"## Template\nExisting codebase detected — Creation did not scaffold the "
            f"'{tid}' template. Work within the current project structure and conventions."
        )

    if tid == "cli":
        (workdir / "pyproject.toml").write_text(
            """[project]
name = "app"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["typer>=0.12.0", "rich>=13.0.0", "fastapi>=0.115.0"]

[project.scripts]
app = "app.main:app"

[tool.pytest.ini_options]
testpaths = ["tests"]
""",
            encoding="utf-8",
        )
        (workdir / "app").mkdir(exist_ok=True)
        (workdir / "app" / "__init__.py").write_text("", encoding="utf-8")
        (workdir / "app" / "main.py").write_text(
            '"""CLI entrypoint."""\nimport typer\n\napp = typer.Typer()\n\n@app.command()\ndef hello():\n    typer.echo("hello")\n\nif __name__ == "__main__":\n    app()\n',
            encoding="utf-8",
        )
        (workdir / "tests").mkdir(exist_ok=True)
        (workdir / "tests" / "test_main.py").write_text(
            "from typer.testing import CliRunner\nfrom app.main import app\n\nrunner = CliRunner()\n\ndef test_hello():\n    r = runner.invoke(app, [\"hello\"])\n    assert r.exit_code == 0\n",
            encoding="utf-8",
        )
        (workdir / "app" / "web.py").write_text(
            'from fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get("/")\ndef root():\n'
            '    return {"product": "app", "cli": "app"}\n',
            encoding="utf-8",
        )
        _write_vercel_python_entrypoint(workdir, "app.web")
        return f"## Template: Python CLI\nBuild on Typer scaffold. Idea: {idea}"

    if tid == "python-api":
        (workdir / "pyproject.toml").write_text(
            """[project]
name = "api"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["fastapi>=0.115.0", "uvicorn[standard]>=0.30.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
""",
            encoding="utf-8",
        )
        (workdir / "api").mkdir(exist_ok=True)
        (workdir / "api" / "__init__.py").write_text("", encoding="utf-8")
        (workdir / "api" / "main.py").write_text(
            'from fastapi import FastAPI\n\napp = FastAPI()\n\n'
            '@app.get("/")\ndef root():\n    return {"product": "api", "ok": True}\n\n'
            '@app.get("/health")\ndef health():\n    return {"ok": True}\n',
            encoding="utf-8",
        )
        (workdir / "tests").mkdir(exist_ok=True)
        (workdir / "tests" / "test_api.py").write_text(
            "from fastapi.testclient import TestClient\nfrom api.main import app\n\ndef test_health():\n    assert TestClient(app).get(\"/health\").json()[\"ok\"]\n",
            encoding="utf-8",
        )
        _write_vercel_python_entrypoint(workdir, "api.main")
        return f"## Template: Python API\nExtend FastAPI scaffold. Idea: {idea}"

    if tid == "nextjs":
        (workdir / "package.json").write_text(
            json_package(idea),
            encoding="utf-8",
        )
        (workdir / "app").mkdir(exist_ok=True)
        (workdir / "app" / "page.tsx").write_text(
            'export default function Home() {\n  return <main><h1>App</h1></main>;\n}\n',
            encoding="utf-8",
        )
        (workdir / "tests").mkdir(exist_ok=True)
        (workdir / "tests" / "smoke.test.js").write_text(
            "test('smoke', () => { expect(1 + 1).toBe(2); });\n",
            encoding="utf-8",
        )
        return f"## Template: Next.js\nExtend app router scaffold. Idea: {idea}"

    if tid == "stripe-saas":
        (workdir / "pyproject.toml").write_text(
            """[project]
name = "stripe-saas"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["fastapi>=0.115.0", "uvicorn[standard]>=0.30.0", "stripe>=11.0.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
""",
            encoding="utf-8",
        )
        (workdir / "app").mkdir(exist_ok=True)
        (workdir / "app" / "main.py").write_text(
            '"""Stripe SaaS scaffold — BuilderShip SDK template."""\n'
            "import os\nimport stripe\nfrom fastapi import FastAPI, Request\n\n"
            "stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')\napp = FastAPI()\n\n"
            '@app.get("/")\ndef root():\n    return {"product": "stripe-saas", "ok": True}\n\n'
            '@app.get("/health")\ndef health():\n    return {"ok": True, "stripe_configured": bool(stripe.api_key)}\n',
            encoding="utf-8",
        )
        (workdir / "tests").mkdir(exist_ok=True)
        (workdir / "tests" / "test_health.py").write_text(
            'from fastapi.testclient import TestClient\nfrom app.main import app\n\n'
            'def test_health():\n    assert TestClient(app).get("/health").json()["ok"]\n',
            encoding="utf-8",
        )
        (workdir / "SPONSOR_SDK.md").write_text(
            "# Stripe (BuilderShip SDK)\n\nSet STRIPE_SECRET_KEY. Implement Checkout + webhook handler.\n",
            encoding="utf-8",
        )
        _write_vercel_python_entrypoint(workdir, "app.main")
        return f"## Template: Stripe SaaS (BuilderShip SDK)\nWire Checkout + webhooks. Idea: {idea}"

    if tid == "qdrant-rag":
        (workdir / "pyproject.toml").write_text(
            """[project]
name = "qdrant-rag"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["qdrant-client>=1.9.0", "fastapi>=0.115.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
""",
            encoding="utf-8",
        )
        (workdir / "rag").mkdir(exist_ok=True)
        (workdir / "rag" / "store.py").write_text(
            '"""Qdrant RAG scaffold — BuilderShip SDK template."""\n'
            "import os\nfrom qdrant_client import QdrantClient\n\n"
            "def client() -> QdrantClient:\n"
            "    url = os.environ.get('QDRANT_URL', 'http://localhost:6333')\n"
            "    return QdrantClient(url=url, api_key=os.environ.get('QDRANT_API_KEY'))\n",
            encoding="utf-8",
        )
        (workdir / "tests").mkdir(exist_ok=True)
        (workdir / "tests" / "test_store.py").write_text(
            "def test_import():\n    from rag.store import client\n    assert callable(client)\n",
            encoding="utf-8",
        )
        (workdir / "SPONSOR_SDK.md").write_text(
            "# Qdrant (BuilderShip SDK)\n\nSet QDRANT_URL + QDRANT_API_KEY. Implement ingest + query.\n",
            encoding="utf-8",
        )
        (workdir / "rag" / "web.py").write_text(
            'from fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get("/")\ndef root():\n'
            '    return {"product": "qdrant-rag", "ok": True}\n',
            encoding="utf-8",
        )
        _write_vercel_python_entrypoint(workdir, "rag.web")
        return f"## Template: Qdrant RAG (BuilderShip SDK)\nBuild retrieval layer. Idea: {idea}"

    if tid == "motherduck-analytics":
        (workdir / "pyproject.toml").write_text(
            """[project]
name = "motherduck-analytics"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["duckdb>=1.0.0", "pandas>=2.0.0", "fastapi>=0.115.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
""",
            encoding="utf-8",
        )
        (workdir / "analytics").mkdir(exist_ok=True)
        (workdir / "analytics" / "pipeline.py").write_text(
            '"""MotherDuck analytics scaffold — BuilderShip SDK template."""\n'
            "import os\nimport duckdb\n\n"
            "def connect():\n"
            "    token = os.environ.get('MOTHERDUCK_TOKEN', '')\n"
            "    uri = f\"md:?motherduck_token={token}\" if token else ':memory:'\n"
            "    return duckdb.connect(uri)\n",
            encoding="utf-8",
        )
        (workdir / "tests").mkdir(exist_ok=True)
        (workdir / "tests" / "test_pipeline.py").write_text(
            "def test_connect():\n    from analytics.pipeline import connect\n    assert connect()\n",
            encoding="utf-8",
        )
        (workdir / "SPONSOR_SDK.md").write_text(
            "# MotherDuck (BuilderShip SDK)\n\nSet MOTHERDUCK_TOKEN. Add SQL transforms + exports.\n",
            encoding="utf-8",
        )
        (workdir / "analytics" / "web.py").write_text(
            'from fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get("/")\ndef root():\n'
            '    return {"product": "motherduck-analytics", "ok": True}\n',
            encoding="utf-8",
        )
        _write_vercel_python_entrypoint(workdir, "analytics.web")
        return f"## Template: MotherDuck analytics (BuilderShip SDK)\nBuild SQL pipeline. Idea: {idea}"

    return ""


def json_package(idea: str) -> str:
    name = "app"
    return f"""{{
  "name": "{name}",
  "version": "0.1.0",
  "private": true,
  "scripts": {{
    "dev": "next dev",
    "build": "next build",
    "test": "node --test tests/"
  }},
  "dependencies": {{
    "next": "^14.0.0",
    "react": "^18.0.0",
    "react-dom": "^18.0.0"
  }}
}}
"""
