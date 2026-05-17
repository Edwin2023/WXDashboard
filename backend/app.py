import threading
import time
import subprocess
import io
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from flask import Flask, render_template, request, jsonify, send_file
from .config import TEMPLATES_DIR, STATIC_DIR, FLASK_HOST, FLASK_PORT, get_wx_file_url, get_wx_file_path
from .database import (
    init_db, get_all_groups, get_group, get_categories,
    get_messages, get_latest_messages, search_messages,
    get_sync_status, get_message_count, get_contacts, get_projects,
    set_subcategory, update_group_category, update_group_settings,
    get_summaries, get_extractions
)
from .sync_engine import sync_incremental, sync_all_groups_full, sync_full, get_sync_stats, discover_new_groups

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)

_auto_sync_thread = None
_auto_sync_interval = 60
_auto_sync_running = False
_auto_sync_last_result = None


def _auto_sync_loop():
    global _auto_sync_running, _auto_sync_last_result
    while _auto_sync_running:
        time.sleep(_auto_sync_interval)
        if not _auto_sync_running:
            break
        try:
            _auto_sync_last_result = sync_incremental()
        except Exception as e:
            _auto_sync_last_result = {"error": str(e)}


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/groups")
def api_groups():
    category = request.args.get("category")
    project = request.args.get("project", "Laldia")
    groups = get_all_groups(category=category, project=project)
    for g in groups:
        g["message_count"] = get_message_count(g["id"])
    return jsonify(groups)


@app.route("/api/groups/<int:group_id>")
def api_group_detail(group_id):
    group = get_group(group_id)
    if not group:
        return jsonify({"error": "群组不存在"}), 404
    group["message_count"] = get_message_count(group_id)
    return jsonify(group)


@app.route("/api/categories")
def api_categories():
    project = request.args.get("project", "Laldia")
    return jsonify(get_categories(project=project))


@app.route("/api/groups/<int:group_id>/messages")
def api_group_messages(group_id):
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    messages, total = get_messages(group_id, limit=limit, offset=offset)
    return jsonify({"messages": messages, "total": total, "limit": limit, "offset": offset})


@app.route("/api/groups/<int:group_id>/messages/latest")
def api_group_latest_messages(group_id):
    n = request.args.get("n", 3, type=int)
    messages = get_latest_messages(group_id, n=n)
    return jsonify(messages)


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "缺少搜索关键词"}), 400
    group_id = request.args.get("group_id", type=int)
    results = search_messages(q, group_id=group_id)
    return jsonify({"query": q, "results": results, "count": len(results)})


@app.route("/api/sync/refresh", methods=["POST"])
def api_sync_refresh():
    try:
        stats = sync_incremental()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sync/pull-all", methods=["POST"])
def api_sync_pull_all():
    group_name = request.args.get("group")
    try:
        if group_name:
            result = sync_full(group_name)
            return jsonify(result)
        else:
            result = sync_all_groups_full()
            return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sync/status")
def api_sync_status():
    stats = get_sync_stats()
    return jsonify(stats)


@app.route("/api/projects")
def api_projects():
    return jsonify(get_projects())


@app.route("/api/groups/<int:group_id>/contacts")
def api_group_contacts(group_id):
    contacts = get_contacts(group_id=group_id)
    return jsonify(contacts)


@app.route("/api/groups/<int:group_id>/summaries")
def api_group_summaries(group_id):
    summaries = get_summaries(group_id)
    return jsonify(summaries)


@app.route("/api/groups/<int:group_id>/extractions")
def api_group_extractions(group_id):
    extractions = get_extractions(group_id)
    return jsonify(extractions)


@app.route("/api/files/check")
def api_check_file():
    msg_date = request.args.get("msg_date", "")
    filename = request.args.get("filename", "")
    url = get_wx_file_url(msg_date, filename)
    if url:
        return jsonify({"exists": True, "url": url})
    return jsonify({"exists": False})


@app.route("/api/files/open", methods=["POST"])
def api_open_file():
    msg_date = request.args.get("msg_date", "")
    filename = request.args.get("filename", "")
    file_path = get_wx_file_path(msg_date, filename)
    if file_path:
        import os as _os
        subprocess.Popen(["explorer", "/select,", _os.path.normpath(file_path)])
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "文件不存在"})


@app.route("/api/groups/<int:group_id>/subcategory", methods=["POST"])
def api_set_subcategory(group_id):
    data = request.get_json(force=True)
    sub = data.get("sub_category", "")
    set_subcategory(group_id, sub)
    return jsonify({"ok": True})


@app.route("/api/groups/<int:group_id>/settings", methods=["GET", "POST"])
def api_group_settings(group_id):
    if request.method == "GET":
        group = get_group(group_id)
        if not group:
            return jsonify({"error": "群组不存在"}), 404
        return jsonify({
            "project": group.get("project", ""),
            "category": group.get("category", ""),
            "sub_category": group.get("sub_category", ""),
            "manual_category": bool(group.get("manual_category", 0)),
            "projects": get_projects(),
            "categories": get_categories()
        })
    data = request.get_json(force=True)
    if data.get("unlock"):
        from .database import unlock_group_category
        unlock_group_category(group_id)
        return jsonify({"ok": True})
    project = data.get("project", "")
    category = data.get("category", "")
    sub_category = data.get("sub_category", "")
    update_group_settings(group_id, project=project, category=category, sub_category=sub_category)
    return jsonify({"ok": True})


@app.route("/api/groups/<int:group_id>/category", methods=["POST"])
def api_set_category(group_id):
    data = request.get_json(force=True)
    cat = data.get("category", "")
    if not cat:
        return jsonify({"error": "分类不能为空"}), 400
    update_group_category(group_id, cat)
    return jsonify({"ok": True, "category": cat})


@app.route("/api/sync/discover", methods=["POST"])
def api_sync_discover():
    try:
        new_groups = discover_new_groups()
        return jsonify({"new_groups": new_groups, "count": len(new_groups)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sync/auto/status")
def api_auto_sync_status():
    return jsonify({
        "running": _auto_sync_running,
        "interval": _auto_sync_interval,
        "last_result": _auto_sync_last_result
    })


@app.route("/api/sync/auto/start", methods=["POST"])
def api_auto_sync_start():
    global _auto_sync_thread, _auto_sync_running, _auto_sync_interval
    data = request.get_json(silent=True) or {}
    interval = int(data.get("interval", 60))
    if interval < 10:
        interval = 10
    _auto_sync_interval = interval

    if _auto_sync_running:
        return jsonify({"running": True, "interval": _auto_sync_interval})

    _auto_sync_running = True
    _auto_sync_thread = threading.Thread(target=_auto_sync_loop, daemon=True)
    _auto_sync_thread.start()
    return jsonify({"running": True, "interval": _auto_sync_interval})


@app.route("/api/sync/auto/stop", methods=["POST"])
def api_auto_sync_stop():
    global _auto_sync_running
    _auto_sync_running = False
    return jsonify({"running": False})


@app.route("/api/export/excel")
def api_export_excel():
    project = request.args.get("project", "Laldia")
    category = request.args.get("category")
    groups = get_all_groups(category=category, project=project)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "微信群台账"

    header_font = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1A1F25", end_color="1A1F25", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin", color="D5DCE4"),
        right=Side(style="thin", color="D5DCE4"),
        top=Side(style="thin", color="D5DCE4"),
        bottom=Side(style="thin", color="D5DCE4"),
    )
    cell_font = Font(name="微软雅黑", size=9, color="3A4454")
    cell_align = Alignment(vertical="top", wrap_text=True)
    name_font = Font(name="微软雅黑", size=9, bold=True, color="1A1F25")
    time_font = Font(name="Consolas", size=9, color="6B7B8D")

    headers = ["#", "群名", "分类", "子分类", "最后活跃", "消息数", "群主", "最近消息", "联系信息"]
    col_widths = [4, 28, 12, 12, 18, 8, 14, 55, 28]

    for ci, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=ci, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border
        ws.column_dimensions[openpyxl.utils.get_column_letter(ci)].width = col_widths[ci - 1]

    for ri, g in enumerate(groups, 1):
        gid = g["id"]
        idx = ri
        name = g.get("name", "")
        cat = g.get("category", "")
        sub = g.get("sub_category", "")
        last_active = g.get("last_active_date", "")
        msg_count = get_message_count(gid)
        creator = g.get("group_creator", "")

        msgs = get_latest_messages(gid, 3)
        msgs_text = ""
        for m in msgs:
            time_part = m["msg_date"] if m["msg_date"] else ""
            sender = m["sender"] if m["sender"] else ""
            content = m["content"] if m["content"] else ""
            content = content.replace("\n", " ").replace("\r", "")
            if len(content) > 120:
                content = content[:120] + "..."
            msgs_text += f"{time_part} {sender}: {content}\n"
        msgs_text = msgs_text.rstrip("\n")

        contacts = get_contacts(group_id=gid)
        contacts_text = "\n".join(
            f"{c['sender_name']} / {c['email']}" if c.get("email") else c.get("sender_name", "")
            for c in contacts[:8]
        )

        row_data = [idx, name, cat, sub, last_active, msg_count, creator, msgs_text, contacts_text]
        for ci, val in enumerate(row_data, 1):
            cell = ws.cell(row=ri + 1, column=ci, value=val if val is not None else "")
            cell.font = name_font if ci == 2 else cell_font
            if ci == 5:
                cell.font = time_font
            cell.alignment = cell_align
            cell.border = thin_border

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    import datetime
    today = datetime.date.today().strftime("%Y%m%d")
    cat_part = category if category else "全部"
    filename = f"WXGLedger_{project}_{cat_part}_{today}.xlsx"

    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )


if __name__ == "__main__":
    init_db()
    print(f"Laldia 微信群台账启动: http://{FLASK_HOST}:{FLASK_PORT}")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=True)
