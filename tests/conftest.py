# Test framework: pytest (Python). We use Flask's built-in test client.
# This conftest provides fixtures to:
#  - Prevent accidental server start by stubbing Flask.run during module load
#  - Load the target module from its file path (tests/test_app.py per PR snippet)
#  - Patch DB connections to use a per-test temporary SQLite file DB
#  - Capture template render calls without requiring actual Jinja templates
#
# We explicitly ignore collecting tests/test_app.py as a test module because it contains the app code.
# These tests focus on the diff-provided file's behaviors (routes, DB interactions, flashes).

import os
import runpy
import sqlite3
import pytest
import flask

# Prevent pytest from importing the app script as a test module

collect_ignore = ["tests/test_app.py"]

@pytest.fixture(scope="session")
def module_path():
    # Path to the module under test, per the PR snippet context
    return os.environ.get("MODULE_UNDER_TEST_PATH", "tests/test_app.py")

@pytest.fixture
def temp_db_path(tmp_path):
    return tmp_path / "test_database.db"

@pytest.fixture
def app_module(monkeypatch, temp_db_path, module_path):
    # Ensure app.run(...) is a no-op during module import
    monkeypatch.setattr(flask.Flask, "run", lambda *_args, **_kwargs: None, raising=True)

    # Execute the module at the given path, getting its globals as a dict
    mod = runpy.run_path(module_path)

    # Patch get_db_connection to use a file-backed temporary SQLite DB
    def _get_db_connection():
        conn = sqlite3.connect(str(temp_db_path))
        conn.row_factory = sqlite3.Row
        return conn
    mod["get_db_connection"] = _get_db_connection

    # Initialize schema
    conn = _get_db_connection()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS posts ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  title TEXT NOT NULL,"
        "  content TEXT"
        ")"
    )
    conn.commit()
    conn.close()

    return mod

@pytest.fixture
def client(app_module):
    app = app_module["app"]
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c

@pytest.fixture
def capture_templates(app_module, monkeypatch):
    """
    Monkeypatch the module's render_template to a stub that records calls.
    Returns a list of call records: {template: str, context: dict}
    """
    calls = []
    def _stub_render(template_name, **context):
        calls.append({"template": template_name, "context": context})
        # Return a simple body so Flask can turn it into a valid Response
        return f"__RENDERED__::{template_name}"
    monkeypatch.setitem(app_module, "render_template", _stub_render)
    return calls

def insert_post(app_module, title, content):
    """Helper to insert a post directly via the patched DB connection."""
    conn = app_module["get_db_connection"]()
    cur = conn.execute("INSERT INTO posts (title, content) VALUES (?, ?)", (title, content))
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id

def fetch_post(app_module, post_id):
    conn = app_module["get_db_connection"]()
    row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    conn.close()
    return row