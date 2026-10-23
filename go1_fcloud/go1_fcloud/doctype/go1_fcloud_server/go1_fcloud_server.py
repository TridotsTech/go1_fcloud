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
    from go1_fcloud.utils import unwrap

    try:
        cloud_servers = unwrap(cloud_get("press.api.server.all")) or []
        local_servers = frappe.get_all(
            "Go1 FCloud Server", fields=["name", "server_name", "server_id"]
        )
        local_by_name = {s["server_name"]: s["name"] for s in local_servers if s.get("server_name")}
        local_by_id = {s["server_id"]: s["name"] for s in local_servers if s.get("server_id")}

        for i in cloud_servers:
            title = i.get("title", "")
            server_id = i.get("name", "")
            plan = i.get("plan") or {}

            # Match by server_id first, then by title
            local_name = local_by_id.get(server_id) or local_by_name.get(title)
            if local_name:
                # Update status and key fields for existing servers
                doc = frappe.get_doc("Go1 FCloud Server", local_name)
                doc.status = i.get("status", "")
                doc.region = i.get("cluster", "")
                if plan:
                    doc.price = plan.get("price_inr", "")
                    doc.vcpu = plan.get("vcpu", "")
                    doc.memory = plan.get("memory", "")
                    doc.disk = plan.get("disk", "")
                if server_id and not doc.server_id:
                    doc.server_id = server_id
                doc.save(ignore_permissions=True)
                frappe.db.commit()
                continue

            # Create new server doc (even without plan data)
            server_doc = frappe.new_doc("Go1 FCloud Server")
            server_doc.status = i.get("status", "")
            server_doc.region = i.get("cluster", "")
            server_doc.server_name = title
            server_doc.server_id = server_id
            if plan:
                server_doc.price = plan.get("price_inr", "")
                server_doc.vcpu = plan.get("vcpu", "")
                server_doc.memory = plan.get("memory", "")
                server_doc.disk = plan.get("disk", "")
            server_doc.insert(ignore_permissions=True)
            frappe.db.commit()

        # Mark local servers deleted from Frappe Cloud
        cloud_titles = {s.get("title", "") for s in cloud_servers}
        cloud_ids = {s.get("name", "") for s in cloud_servers}
        for local in local_servers:
            if local["server_name"] not in cloud_titles and local.get("server_id") not in cloud_ids:
                frappe.db.set_value(
                    "Go1 FCloud Server", local["name"], "status", "Deleted"
                )
        frappe.db.commit()

    except Exception:
        frappe.log_error("Sync Server Error", frappe.get_traceback())
