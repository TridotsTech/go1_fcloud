# Copyright (c) 2024, Tridots Tech and contributors
# For license information, please see license.txt

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


def sync_server():
    try:
        data = cloud_get("press.api.server.all")
        cloud_servers = data.get("message", []) or []
        local_servers = frappe.get_all(
            "Go1 FCloud Server", fields=["name", "server_name"]
        )
        local_by_name = {s["server_name"]: s["name"] for s in local_servers}

        for i in cloud_servers:
            title = i.get("title", "")
            plan = i.get("plan") or {}

            if title in local_by_name:
                # Update status and key fields for existing servers
                doc = frappe.get_doc("Go1 FCloud Server", local_by_name[title])
                doc.status = i.get("status", "")
                doc.region = i.get("cluster", "")
                if plan:
                    doc.price = plan.get("price_inr", "")
                    doc.vcpu = plan.get("vcpu", "")
                    doc.memory = plan.get("memory", "")
                    doc.disk = plan.get("disk", "")
                if i.get("name") and not doc.server_id:
                    doc.server_id = i["name"]
                doc.save(ignore_permissions=True)
                frappe.db.commit()
                continue

            if plan:
                server_doc = frappe.new_doc("Go1 FCloud Server")
                server_doc.status = i.get("status", "")
                server_doc.region = i.get("cluster", "")
                server_doc.price = plan.get("price_inr", "")
                server_doc.server_name = title
                server_doc.server_id = i.get("name", "")
                server_doc.vcpu = plan.get("vcpu", "")
                server_doc.memory = plan.get("memory", "")
                server_doc.disk = plan.get("disk", "")
                server_doc.insert(ignore_permissions=True)
                frappe.db.commit()

        # Mark local servers deleted from Frappe Cloud
        cloud_titles = {s.get("title", "") for s in cloud_servers}
        for local in local_servers:
            if local["server_name"] not in cloud_titles:
                frappe.db.set_value(
                    "Go1 FCloud Server", local["name"], "status", "Deleted"
                )
        frappe.db.commit()

    except Exception:
        frappe.log_error("Sync Server Error", frappe.get_traceback())
