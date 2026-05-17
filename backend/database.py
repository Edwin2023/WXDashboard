import sqlite3
import os
from .config import DB_PATH, DATA_DIR


def get_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL,
            sub_category TEXT,
            project TEXT DEFAULT 'Laldia',
            partner_full_name TEXT,
            main_purpose TEXT,
            notes TEXT,
            group_creator TEXT,
            last_active_date TEXT,
            total_messages INTEGER DEFAULT 0,
            deleted INTEGER DEFAULT 0
        );
    """)
    try:
        conn.execute("ALTER TABLE groups ADD COLUMN sub_category TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE groups ADD COLUMN project TEXT DEFAULT 'Laldia'")
    except sqlite3.OperationalError:
        pass
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES groups(id),
            local_id INTEGER,
            sender TEXT NOT NULL,
            content TEXT NOT NULL,
            msg_time TEXT NOT NULL,
            msg_date TEXT NOT NULL,
            msg_type TEXT DEFAULT 'text',
            raw_json TEXT,
            UNIQUE(group_id, local_id)
        );
        CREATE INDEX IF NOT EXISTS idx_msg_group_date ON messages(group_id, msg_date);
        CREATE INDEX IF NOT EXISTS idx_msg_group_time ON messages(group_id, msg_time DESC);

        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            group_name, sender, content,
            content=messages, content_rowid=id
        );

        CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, group_name, sender, content)
            VALUES (new.id,
                (SELECT name FROM groups WHERE id = new.group_id),
                new.sender, new.content);
        END;

        CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, group_name, sender, content)
            VALUES('delete', old.id, old.sender, old.content, old.content);
        END;

        CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, group_name, sender, content)
            VALUES('delete', old.id, old.sender, old.content, old.content);
            INSERT INTO messages_fts(rowid, group_name, sender, content)
            VALUES (new.id,
                (SELECT name FROM groups WHERE id = new.group_id),
                new.sender, new.content);
        END;

        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER REFERENCES groups(id),
            sender_name TEXT NOT NULL,
            display_name TEXT,
            email TEXT,
            phone TEXT,
            company TEXT,
            source_message_id INTEGER REFERENCES messages(id),
            extraction_method TEXT DEFAULT 'regex',
            confirmed INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_name TEXT NOT NULL,
            sync_time TEXT NOT NULL,
            since_date TEXT,
            messages_pulled INTEGER DEFAULT 0,
            messages_new INTEGER DEFAULT 0,
            status TEXT,
            error_msg TEXT
        );
    """)
    conn.commit()
    conn.close()


def get_all_groups(category=None, project=None):
    conn = get_db()
    clauses = ["deleted=0"]
    params = []
    if category:
        clauses.append("category=?")
        params.append(category)
    if project:
        clauses.append("project=?")
        params.append(project)
    sql = f"SELECT * FROM groups WHERE {' AND '.join(clauses)} ORDER BY last_active_date DESC, id DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_group(group_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM groups WHERE id=?", (group_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_group_by_name(name):
    conn = get_db()
    row = conn.execute("SELECT * FROM groups WHERE name=?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_group(name, category, sub_category=None, partner_full_name=None, main_purpose=None,
                 notes=None, group_creator=None, project=None):
    conn = get_db()
    existing = conn.execute("SELECT id FROM groups WHERE name=?", (name,)).fetchone()
    if existing:
        conn.execute("""
            UPDATE groups SET category=?, sub_category=?, partner_full_name=?, main_purpose=?,
            notes=?, group_creator=?
            WHERE id=?
        """, (category, sub_category, partner_full_name, main_purpose, notes, group_creator, existing["id"]))
        gid = existing["id"]
    else:
        cur = conn.execute("""
            INSERT INTO groups (name, category, sub_category, partner_full_name, main_purpose,
                              notes, group_creator, project)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, category, sub_category, partner_full_name, main_purpose, notes, group_creator, project))
        gid = cur.lastrowid
    conn.commit()
    conn.close()
    return gid


def update_group_stats(group_id, last_active_date=None, total_messages=None, conn=None):
    close_conn = conn is None
    if conn is None:
        conn = get_db()
    if last_active_date and total_messages is not None:
        conn.execute(
            "UPDATE groups SET last_active_date=?, total_messages=? WHERE id=?",
            (last_active_date, total_messages, group_id)
        )
    elif last_active_date:
        conn.execute(
            "UPDATE groups SET last_active_date=? WHERE id=?",
            (last_active_date, group_id)
        )
    elif total_messages is not None:
        conn.execute(
            "UPDATE groups SET total_messages=? WHERE id=?",
            (total_messages, group_id)
        )
    conn.commit()
    if close_conn:
        conn.close()


def get_categories(project=None):
    conn = get_db()
    if project:
        rows = conn.execute(
            "SELECT DISTINCT category FROM groups WHERE deleted=0 AND project=? ORDER BY category",
            (project,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT category FROM groups WHERE deleted=0 ORDER BY category"
        ).fetchall()
    conn.close()
    return [r["category"] for r in rows]


def get_messages(group_id, limit=50, offset=0):
    conn = get_db()
    rows = conn.execute("""
        SELECT id, group_id, local_id, sender, content, msg_time, msg_date, msg_type
        FROM messages WHERE group_id=? ORDER BY msg_time DESC LIMIT ? OFFSET ?
    """, (group_id, limit, offset)).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) as cnt FROM messages WHERE group_id=?", (group_id,)
    ).fetchone()["cnt"]
    conn.close()
    return [dict(r) for r in rows], total


def get_latest_messages(group_id, n=3):
    conn = get_db()
    rows = conn.execute("""
        SELECT id, group_id, local_id, sender, content, msg_time, msg_date, msg_type
        FROM messages WHERE group_id=? AND msg_type != '系统'
        ORDER BY msg_time DESC LIMIT ?
    """, (group_id, n)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_message(group_id, local_id, sender, content, msg_time, msg_date,
                   msg_type='text', raw_json=None):
    conn = get_db()
    conn.execute("""
        INSERT OR IGNORE INTO messages (group_id, local_id, sender, content, msg_time,
                                        msg_date, msg_type, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (group_id, local_id, sender, content, msg_time, msg_date, msg_type, raw_json))
    conn.commit()
    conn.close()


def get_message_count(group_id):
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM messages WHERE group_id=?", (group_id,)
    ).fetchone()
    conn.close()
    return row["cnt"]


def search_messages(q, group_id=None):
    conn = get_db()
    if group_id:
        rows = conn.execute("""
            SELECT m.id, m.group_id, m.sender, m.content, m.msg_time, m.msg_date,
                   g.name as group_name
            FROM messages_fts
            JOIN messages m ON messages_fts.rowid = m.id
            JOIN groups g ON m.group_id = g.id
            WHERE m.group_id=? AND messages_fts MATCH ?
            ORDER BY m.msg_time DESC LIMIT 100
        """, (group_id, q)).fetchall()
    else:
        rows = conn.execute("""
            SELECT m.id, m.group_id, m.sender, m.content, m.msg_time, m.msg_date,
                   g.name as group_name
            FROM messages_fts
            JOIN messages m ON messages_fts.rowid = m.id
            JOIN groups g ON m.group_id = g.id
            WHERE messages_fts MATCH ?
            ORDER BY m.msg_time DESC LIMIT 100
        """, (q,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_sync_log(group_name, since_date, messages_pulled, messages_new, status, error_msg=None):
    from datetime import datetime
    conn = get_db()
    conn.execute("""
        INSERT INTO sync_log (group_name, sync_time, since_date, messages_pulled,
                              messages_new, status, error_msg)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (group_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), since_date,
          messages_pulled, messages_new, status, error_msg))
    conn.commit()
    conn.close()


def get_sync_status(limit=50):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_group_names():
    conn = get_db()
    rows = conn.execute("SELECT name FROM groups WHERE deleted=0 ORDER BY id").fetchall()
    conn.close()
    return [r["name"] for r in rows]


def get_contacts(group_id=None):
    conn = get_db()
    if group_id:
        rows = conn.execute(
            "SELECT * FROM contacts WHERE group_id=? ORDER BY id", (group_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM contacts ORDER BY group_id, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_projects():
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT project FROM groups WHERE deleted=0 AND project IS NOT NULL ORDER BY project"
    ).fetchall()
    conn.close()
    return [r["project"] for r in rows]


def set_subcategory(group_id, sub_category):
    conn = get_db()
    conn.execute("UPDATE groups SET sub_category=? WHERE id=?", (sub_category, group_id))
    conn.commit()
    conn.close()
