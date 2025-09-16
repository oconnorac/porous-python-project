# Test framework: pytest (Python). Uses Flask test client.
# Focus: Validate behaviors in the diff-provided Flask app (CRUD routes, flash messages, error paths).
# Strategy: Run the target module via runpy with Flask.run stubbed, patch DB to temp file, and stub render_template.

import sqlite3
import pytest

# -------- Index route --------

def test_index_empty_database_renders_index_template_with_no_posts(client, capture_templates):
    resp = client.get("/")
    assert resp.status_code == 200
    assert capture_templates, "render_template should be called"
    last = capture_templates[-1]
    assert last["template"] == "index.html"
    assert last["context"]["posts"] == []

def test_index_with_posts_renders_all_posts(client, app_module, capture_templates):
    # Insert sample posts
    from conftest import insert_post
    insert_post(app_module, "Hello", "World")
    insert_post(app_module, "Foo", "Bar")

    resp = client.get("/")
    assert resp.status_code == 200
    last = capture_templates[-1]
    assert last["template"] == "index.html"
    posts = last["context"]["posts"]
    assert len(posts) == 2
    titles = [row["title"] for row in posts]
    assert set(titles) == {"Hello", "Foo"}

# -------- Post detail route --------

def test_post_detail_existing_renders_post_template(client, app_module, capture_templates):
    from conftest import insert_post
    pid = insert_post(app_module, "Title A", "Content A")

    resp = client.get(f"/{pid}")
    assert resp.status_code == 200
    last = capture_templates[-1]
    assert last["template"] == "post.html"
    assert last["context"]["post"]["id"] == pid
    assert last["context"]["post"]["title"] == "Title A"

def test_post_detail_missing_returns_404(client):
    resp = client.get("/999999")
    assert resp.status_code == 404

# -------- Create route --------

def test_create_get_renders_form(client, capture_templates):
    resp = client.get("/create")
    assert resp.status_code == 200
    assert capture_templates[-1]["template"] == "create.html"

def test_create_post_missing_title_flashes_and_rerenders(client, capture_templates):
    resp = client.post("/create", data={"title": "", "content": "Body"}, follow_redirects=False)
    # Should not redirect; should re-render with a flash message
    assert resp.status_code == 200
    # Flash message stored in session
    with client.session_transaction() as sess:
        flashes = list(sess.get("_flashes", []))
    assert flashes, "Expected a flashed message"
    categories = [c for (c, m) in flashes]
    messages = [m for (c, m) in flashes]
    assert "message" in categories
    assert "Title is required\!" in messages
    assert capture_templates[-1]["template"] == "create.html"

def test_create_post_success_inserts_and_redirects(client, app_module):
    resp = client.post("/create", data={"title": "New Post", "content": "Body"}, follow_redirects=False)
    assert resp.status_code in (301, 302)
    assert resp.headers.get("Location", "").endswith("/")

    # Verify DB mutation
    conn = app_module["get_db_connection"]()
    rows = conn.execute("SELECT * FROM posts WHERE title = ?", ("New Post",)).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["content"] == "Body"

def test_create_post_whitespace_title_is_accepted_per_current_logic(client, app_module):
    # Current code treats non-empty strings (even whitespace) as valid
    resp = client.post("/create", data={"title": "   ", "content": "X"}, follow_redirects=False)

    assert resp.status_code in (301, 302)

    conn = app_module["get_db_connection"]()
    row = conn.execute("SELECT * FROM posts ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert row is not None
    assert row["title"] == "   "

# -------- Edit route --------

def test_edit_get_renders_form_with_post(client, app_module, capture_templates):
    from conftest import insert_post
    pid = insert_post(app_module, "Old", "Body")
    resp = client.get(f"/{pid}/edit")
    assert resp.status_code == 200
    last = capture_templates[-1]
    assert last["template"] == "edit.html"
    assert last["context"]["post"]["id"] == pid
    assert last["context"]["post"]["title"] == "Old"

def test_edit_post_missing_title_flashes_and_rerenders(client, app_module, capture_templates):
    from conftest import insert_post
    pid = insert_post(app_module, "Old", "Body")
    resp = client.post(f"/{pid}/edit", data={"title": "", "content": "B"}, follow_redirects=False)
    assert resp.status_code == 200
    with client.session_transaction() as sess:
        flashes = list(sess.get("_flashes", []))
    assert flashes, "Expected a flashed message for missing title"
    assert any(m == "Title is required\!" for (_, m) in flashes)
    assert capture_templates[-1]["template"] == "edit.html"

def test_edit_post_success_updates_and_redirects(client, app_module):
    from conftest import insert_post, fetch_post
    pid = insert_post(app_module, "Old", "Body")
    resp = client.post(f"/{pid}/edit", data={"title": "Updated", "content": "B2"}, follow_redirects=False)
    assert resp.status_code in (301, 302)
    assert resp.headers.get("Location", "").endswith("/")

    row = fetch_post(app_module, pid)
    assert row["title"] == "Updated"
    assert row["content"] == "B2"

# -------- Delete route --------

def test_delete_post_success_redirects_and_flashes(client, app_module):
    from conftest import insert_post, fetch_post
    pid = insert_post(app_module, "To Delete", "D")
    resp = client.post(f"/{pid}/delete", follow_redirects=False)
    assert resp.status_code in (301, 302)
    assert resp.headers.get("Location", "").endswith("/")

    # Verify deletion
    assert fetch_post(app_module, pid) is None

    # Verify flash message
    with client.session_transaction() as sess:
        flashes = list(sess.get("_flashes", []))
    assert flashes, "Expected a flash after delete"
    messages = [m for (_, m) in flashes]
    assert '"To Delete" was successfully deleted!' in messages

def test_delete_post_missing_returns_404(client):
    resp = client.post("/999999/delete", follow_redirects=False)
    assert resp.status_code == 404