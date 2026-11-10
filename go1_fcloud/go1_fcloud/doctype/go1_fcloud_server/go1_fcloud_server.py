# Copyright (c) 2024, Tridots Tech and contributors
# For license information, please see license.txt

import re

import frappe
from frappe.model.document import Document
from go1_fcloud.utils import cloud_get


class Go1FCloudServer(Document):
    pass


@frappe.whitelist()
def sync_server_enqueue():
    try:
        frappe.enqueue(sync_server, queue="long")
    except Exception:
        frappe.log_error("sync server enqueue error", frappe.get_traceback())


def _extract_server_number(server_id):
    """Extract the numeric part from a server ID like 'f960-mumbai' or 'm960-mumbai'.

    Returns the number string (e.g. '960') or None.
    """
    m = re.match(r"^[fm](\d+)", server_id or "")
    return m.group(1) if m else None


def sync_server():
    from go1_fcloud.utils import unwrap

    try:
        cloud_servers = unwrap(cloud_get("press.api.server.all")) or []

        # Separate app servers (f-prefix) and db servers (m-prefix)
        app_servers = []
        db_servers_by_num = {}
        for s in cloud_servers:
            server_id = s.get("name", "")
            if server_id.startswith("m"):
                num = _extract_server_number(server_id)
                if num:
                    db_servers_by_num[num] = s
            else:
                app_servers.append(s)

        # Step 1: Remove stale DB-only docs (m-prefix server_id) created by old sync
        existing = frappe.get_all(
            "Go1 FCloud Server",
            fields=["name", "server_id"],
        )
        for row in existing:
            sid = row.get("server_id") or ""
            if sid.startswith("m"):
                try:
                    frappe.delete_doc(
                        "Go1 FCloud Server", row["name"],
                        ignore_permissions=True, force=True,
                    )
                except Exception:
                    frappe.log_error(
                        f"sync_server:pre_cleanup:{row['name']}", frappe.get_traceback()
                    )
        frappe.db.commit()

        # Step 2: Build local lookup (after pre-cleanup)
        local_servers = frappe.get_all(
            "Go1 FCloud Server",
            fields=["name", "server_name", "server_id", "db_server_id"],
        )
        local_by_id = {s["server_id"]: s["name"] for s in local_servers if s.get("server_id")}
        local_by_name = {s["server_name"]: s["name"] for s in local_servers if s.get("server_name")}

        # Step 3: Create/update one doc per app server, paired with its db server
        for app in app_servers:
            title = app.get("title", "")
            app_id = app.get("name", "")
            app_plan = app.get("plan") or {}

            # Find paired db server by matching number (f960 ↔ m960)
            num = _extract_server_number(app_id)
            db = db_servers_by_num.get(num, {}) if num else {}
            db_id = db.get("name", "")
            db_plan = db.get("plan") or {}

            # Match existing local doc
            local_name = local_by_id.get(app_id) or local_by_name.get(title)
            if local_name:
                try:
                    doc = frappe.get_doc("Go1 FCloud Server", local_name)
                    doc.status = app.get("status", "")
                    doc.region = app.get("cluster", "")
                    if app_id and not doc.server_id:
                        doc.server_id = app_id
                    # App plan
                    if app_plan:
                        doc.price = app_plan.get("price_inr", "")
                        doc.vcpu = app_plan.get("vcpu", "")
                        doc.memory = app_plan.get("memory", "")
                        doc.disk = app_plan.get("disk", "")
                    # DB server
                    if db_id:
                        doc.db_server_id = db_id
                    if db_plan:
                        doc.db_price = db_plan.get("price_inr", "")
                        doc.db_vcpu = db_plan.get("vcpu", "")
                        doc.db_memory = db_plan.get("memory", "")
                        doc.db_disk = db_plan.get("disk", "")
                    doc.save(ignore_permissions=True)
                    frappe.db.commit()
                except Exception:
                    frappe.log_error(
                        f"sync_server:update:{app_id}", frappe.get_traceback()
                    )
                continue

            # Create new server doc
            try:
                doc = frappe.new_doc("Go1 FCloud Server")
                doc.server_name = title
                doc.server_id = app_id
                doc.status = app.get("status", "")
                doc.region = app.get("cluster", "")
                if app_plan:
                    doc.price = app_plan.get("price_inr", "")
                    doc.vcpu = app_plan.get("vcpu", "")
                    doc.memory = app_plan.get("memory", "")
                    doc.disk = app_plan.get("disk", "")
                if db_id:
                    doc.db_server_id = db_id
                if db_plan:
                    doc.db_price = db_plan.get("price_inr", "")
                    doc.db_vcpu = db_plan.get("vcpu", "")
                    doc.db_memory = db_plan.get("memory", "")
                    doc.db_disk = db_plan.get("disk", "")
                doc.insert(ignore_permissions=True)
                frappe.db.commit()
            except Exception:
                frappe.log_error(
                    f"sync_server:create:{app_id}", frappe.get_traceback()
                )

        # Step 4: Remove local servers not in cloud
        local_servers = frappe.get_all(
            "Go1 FCloud Server", fields=["name", "server_name", "server_id"]
        )
        cloud_app_titles = {s.get("title", "") for s in app_servers}
        cloud_app_titles.discard("")
        cloud_app_ids = {s.get("name", "") for s in app_servers}
        cloud_app_ids.discard("")

        for local in local_servers:
            title_match = local.get("server_name") and local["server_name"] in cloud_app_titles
            id_match = local.get("server_id") and local["server_id"] in cloud_app_ids
            if not title_match and not id_match:
                try:
                    frappe.delete_doc(
                        "Go1 FCloud Server",
                        local["name"],
                        ignore_permissions=True,
                        force=True,
                    )
                except Exception:
                    frappe.log_error(
                        f"sync_server:delete:{local['name']}", frappe.get_traceback()
                    )
        frappe.db.commit()

    except Exception:
        frappe.log_error("Sync Server Error", frappe.get_traceback())
