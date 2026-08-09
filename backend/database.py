import sqlite3
import os
from .config import DB_PATH, DATA_DIR, MY_WECHAT_NAME, MY_EMAIL_KEYWORD


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
            deleted INTEGER DEFAULT 0,
            last_extraction_time TEXT
        );
    """)
    try:
        conn.execute("ALTER TABLE groups ADD COLUMN sub_category TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE groups ADD COLUMN manual_category INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE groups ADD COLUMN last_extraction_time TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE groups ADD COLUMN project TEXT DEFAULT 'Laldia'")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE groups ADD COLUMN chat_type TEXT DEFAULT 'group'")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE groups ADD COLUMN backfill_failed INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN extracted INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN file_downloaded INTEGER DEFAULT 0")
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
            group_name, sender, content
        );

        CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, group_name, sender, content)
            VALUES (new.id,
                (SELECT name FROM groups WHERE id = new.group_id),
                new.sender, new.content);
        END;

        CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
            DELETE FROM messages_fts WHERE rowid = old.id;
        END;

        CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
            DELETE FROM messages_fts WHERE rowid = old.id;
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


def get_all_groups(category=None, project=None, group_creator=None, with_details=False):
    conn = get_db()
    clauses = ["g.deleted=0"]
    params = []
    if category:
        clauses.append("g.category=?")
        params.append(category)
    if project:
        clauses.append("g.project=?")
        params.append(project)
    if group_creator:
        clauses.append("g.group_creator=?")
        params.append(group_creator)
    where = " AND ".join(clauses)
    sql = f"""
        SELECT g.*, COALESCE(mc.cnt, 0) as message_count
        FROM groups g
        LEFT JOIN (
            SELECT group_id, COUNT(*) as cnt FROM messages GROUP BY group_id
        ) mc ON mc.group_id = g.id
        WHERE {where}
        ORDER BY g.last_active_date DESC, g.id DESC
    """
    rows = conn.execute(sql, params).fetchall()
    groups = [dict(r) for r in rows]

    if with_details and groups:
        group_ids = [g["id"] for g in groups]
        placeholders = ",".join("?" for _ in group_ids)
        # 批量获取每个群最近3条非系统消息
        latest = conn.execute(f"""
            SELECT group_id, sender, content, msg_time, msg_date, msg_type, raw_json
            FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY group_id ORDER BY msg_time DESC
                ) as rn
                FROM messages
                WHERE group_id IN ({placeholders}) AND msg_type != '系统'
            ) WHERE rn <= 3
        """, group_ids).fetchall()
        latest_by_group = {}
        for r in latest:
            latest_by_group.setdefault(r["group_id"], []).append(dict(r))
        for g in groups:
            g["latest_messages"] = latest_by_group.get(g["id"], [])

        # 批量获取所有联系人
        contacts = conn.execute(f"""
            SELECT * FROM contacts
            WHERE group_id IN ({placeholders})
              AND sender_name IS NOT ?
              AND (email IS NULL OR email NOT LIKE ?)
            ORDER BY group_id, id
        """, (*group_ids, MY_WECHAT_NAME, "%" + MY_EMAIL_KEYWORD + "%")).fetchall()
        contacts_by_group = {}
        for r in contacts:
            contacts_by_group.setdefault(r["group_id"], []).append(dict(r))
        for g in groups:
            g["contacts"] = contacts_by_group.get(g["id"], [])

    conn.close()
    return groups


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
                 notes=None, group_creator=None, project=None, chat_type="group"):
    conn = get_db()
    existing = conn.execute("SELECT id, manual_category FROM groups WHERE name=?", (name,)).fetchone()
    if existing:
        if existing["manual_category"]:
            conn.execute("""
                UPDATE groups SET sub_category=?, partner_full_name=?, main_purpose=?,
                notes=?, group_creator=?, chat_type=?
                WHERE id=?
            """, (sub_category, partner_full_name, main_purpose, notes, group_creator, chat_type, existing["id"]))
        else:
            conn.execute("""
                UPDATE groups SET category=?, sub_category=?, partner_full_name=?, main_purpose=?,
                notes=?, group_creator=?, project=?, chat_type=?
                WHERE id=?
            """, (category, sub_category, partner_full_name, main_purpose, notes, group_creator, project, chat_type, existing["id"]))
        gid = existing["id"]
    else:
        cur = conn.execute("""
            INSERT INTO groups (name, category, sub_category, partner_full_name, main_purpose,
                              notes, group_creator, project, chat_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, category, sub_category, partner_full_name, main_purpose, notes, group_creator, project, chat_type))
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


def update_group_category(group_id, category):
    conn = get_db()
    conn.execute(
        "UPDATE groups SET category=?, manual_category=1 WHERE id=?",
        (category, group_id)
    )
    conn.commit()
    conn.close()


def update_group_settings(group_id, project=None, category=None, sub_category=None):
    conn = get_db()
    conn.execute(
        "UPDATE groups SET project=?, category=?, sub_category=?, manual_category=1 WHERE id=?",
        (project, category, sub_category, group_id)
    )
    conn.commit()
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
        SELECT id, group_id, local_id, sender, content, msg_time, msg_date, msg_type, raw_json
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
        SELECT id, group_id, local_id, sender, content, msg_time, msg_date, msg_type, raw_json
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
            "SELECT * FROM contacts WHERE group_id=? AND sender_name IS NOT ? AND (email IS NULL OR email NOT LIKE ?) ORDER BY id",
            (group_id, MY_WECHAT_NAME, "%" + MY_EMAIL_KEYWORD + "%")
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM contacts WHERE sender_name IS NOT ? AND (email IS NULL OR email NOT LIKE ?) ORDER BY group_id, id",
            (MY_WECHAT_NAME, "%" + MY_EMAIL_KEYWORD + "%")
        ).fetchall()
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
    conn.execute(
        "UPDATE groups SET sub_category=?, manual_category=1 WHERE id=?",
        (sub_category, group_id)
    )
    conn.commit()
    conn.close()


def unlock_group_category(group_id):
    conn = get_db()
    conn.execute("UPDATE groups SET manual_category=0 WHERE id=?", (group_id,))
    conn.commit()
    conn.close()
    conn.commit()
    conn.close()


def get_summaries(group_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM ai_summaries WHERE group_id=? ORDER BY generated_at DESC",
        (group_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_extractions(group_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM ai_extractions WHERE group_id=? ORDER BY extract_type, id",
        (group_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_messages_for_ai_processing(group_id, date_from=None, date_to=None, max_messages=200, unextracted_only=False):
    """AI处理用消息读取。按时间正序分页，排除系统消息。供分类/摘要/提取技能从SQLite读取，替代wx-cli调用。"""
    conn = get_db()
    clauses = ["group_id=?", "msg_type != '系统'"]
    params = [group_id]

    if unextracted_only:
        clauses.append("extracted=0")
    if date_from:
        clauses.append("msg_time >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("msg_time <= ?")
        params.append(date_to)

    where = " AND ".join(clauses)
    rows = conn.execute(f"""
        SELECT id, sender, content, msg_time, msg_date, msg_type
        FROM messages WHERE {where}
        ORDER BY msg_time ASC LIMIT ?
    """, params + [max_messages]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_messages_extracted(group_id, message_ids=None, up_to_id=None):
    """标记消息为已提取。可指定消息ID列表或上限ID（标记该群该ID及之前所有消息）。"""
    conn = get_db()
    if message_ids:
        placeholders = ",".join("?" for _ in message_ids)
        conn.execute(f"""
            UPDATE messages SET extracted=1 WHERE group_id=? AND id IN ({placeholders})
        """, [group_id] + message_ids)
    elif up_to_id:
        # 逐条更新避免 FTS 触发器在范围更新时出错
        rows = conn.execute(
            "SELECT id FROM messages WHERE group_id=? AND id <= ? AND extracted=0",
            (group_id, up_to_id)
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"""
                UPDATE messages SET extracted=1 WHERE id IN ({placeholders})
            """, ids)
    conn.commit()
    conn.close()


def get_unextracted_message_count(group_id):
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM messages WHERE group_id=? AND extracted=0 AND msg_type != '系统'",
        (group_id,)
    ).fetchone()
    conn.close()
    return row["cnt"]


def update_extraction_time(group_id):
    conn = get_db()
    conn.execute(
        "UPDATE groups SET last_extraction_time=? WHERE id=?",
        (__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S'), group_id)
    )
    conn.commit()
    conn.close()


def get_groups_for_incremental_extraction():
    """返回需要增量提取的群：该群存在未提取的消息。"""
    conn = get_db()
    rows = conn.execute("""
        SELECT g.id, g.name, g.category, g.project, g.total_messages,
               g.last_extraction_time, g.last_active_date,
               COALESCE(ue.cnt, 0) as unextracted_count
        FROM groups g
        LEFT JOIN (
            SELECT group_id, COUNT(*) as cnt
            FROM messages
            WHERE extracted=0 AND msg_type != '系统'
            GROUP BY group_id
        ) ue ON ue.group_id = g.id
        WHERE g.deleted = 0 AND ue.cnt > 0
        ORDER BY
            CASE WHEN g.last_extraction_time IS NULL THEN 0 ELSE 1 END,
            g.total_messages DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_group_message_stats():
    """获取所有群的消息统计，供AI技能决定处理哪些群。"""
    conn = get_db()
    rows = conn.execute("""
        SELECT g.id, g.name, g.category, g.project,
               COUNT(m.id) as msg_count,
               MIN(m.msg_date) as earliest,
               MAX(m.msg_date) as latest
        FROM groups g
        LEFT JOIN messages m ON m.group_id = g.id
        WHERE g.deleted = 0
        GROUP BY g.id
        ORDER BY msg_count DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_groups_for_classification():
    """获取待分类群及其最近5条样本消息，供AI分类使用。"""
    conn = get_db()
    groups = conn.execute("""
        SELECT id, name, category FROM groups
        WHERE deleted=0 AND (category IS NULL OR category = '' OR category = '其他')
        ORDER BY id
    """).fetchall()

    result = []
    for g in groups:
        msgs = conn.execute("""
            SELECT sender, content, msg_date FROM messages
            WHERE group_id=? AND msg_type != '系统'
            ORDER BY msg_time DESC LIMIT 5
        """, (g["id"],)).fetchall()
        result.append({
            "id": g["id"],
            "name": g["name"],
            "category": g["category"],
            "sample_messages": [dict(m) for m in msgs]
        })
    conn.close()
    return result


def get_undownloaded_file_messages():
    """获取所有未下载的文件消息（排除图片、语音、视频、链接/卡片），含群组信息。"""
    conn = get_db()
    rows = conn.execute("""
        SELECT m.id, m.group_id, m.sender, m.content, m.msg_time, m.msg_date, m.raw_json,
               g.name as group_name, g.category, g.project
        FROM messages m
        JOIN groups g ON m.group_id = g.id
        WHERE m.file_downloaded = 0
          AND m.content LIKE '%[文件]%'
          AND m.sender != ?
        ORDER BY m.msg_time ASC
    """, (MY_WECHAT_NAME,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_files_downloaded(message_ids):
    """批量标记消息为已下载。"""
    if not message_ids:
        return
    conn = get_db()
    placeholders = ",".join("?" for _ in message_ids)
    conn.execute(f"""
        UPDATE messages SET file_downloaded=1 WHERE id IN ({placeholders})
    """, message_ids)
    conn.commit()
    conn.close()
