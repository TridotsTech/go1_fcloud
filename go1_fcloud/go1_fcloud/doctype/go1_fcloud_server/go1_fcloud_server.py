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
        local_server = frappe.get_all("Go1 FCloud Server", fields=["*"])

        def search(name, local_list):
            return ["found" for server in local_list if server["server_name"] == name]

        for i in data["message"]:
            res = search(i["title"], local_server)
            if not res:
                if i["plan"]:
                    server_doc = frappe.new_doc("Go1 FCloud Server")
                    server_doc.status = i["status"]
                    server_doc.region = i["cluster"]
                    server_doc.price = i["plan"]["price_inr"] if i["plan"] else ""
                    server_doc.server_name = i["title"]
                    server_doc.server_id = i["name"]
                    server_doc.vcpu = i["plan"]["vcpu"] if i["plan"] else ""
                    server_doc.memory = i["plan"]["memory"] if i["plan"] else ""
                    server_doc.disk = i["plan"]["disk"] if i["plan"] else ""
                    server_doc.insert(ignore_permissions=True)
    except Exception:
        frappe.log_error("Sync Server Error", frappe.get_traceback())
