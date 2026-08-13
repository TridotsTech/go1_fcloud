# Copyright (c) 2024, Tridots Tech and contributors
# For license information, please see license.txt

import frappe
from datetime import datetime
from frappe.model.document import Document
from go1_fcloud.utils import cloud_get, cloud_post, unwrap


class Go1FCloudInvoice(Document):
    pass


@frappe.whitelist()
def sync_invoices_queue():
    frappe.enqueue(invoice_sync, queue="long")


def invoice_sync():
    try:
        total_params = {
            "doctype": "Invoice",
            "fields": [
                "name",
                "type",
                "invoice_pdf",
                "payment_mode",
                "stripe_invoice_url",
                "name",
                "status",
                "due_date",
                "total",
                "amount_paid",
                "amount_due",
                "period_start",
                "period_end",
            ],
            "filters": {},
            "order_by": "due_date desc",
            "start": 0,
            "limit": 20,
            "limit_start": 0,
            "limit_page_length": 20,
            "debug": 0,
        }
        invoices_response = cloud_post("press.api.client.get_list", params=total_params)
        local_invoice = frappe.get_all("Go1 FCloud Invoice", fields=["*"])

        # frappe.log_error("invoice_response",str(invoices_response))
        # frappe.log_error("local_invoice",str(local_invoice))
        def search(name, local_list):
            return ["found" for inv in local_list if inv["name"] == name]

        for i in invoices_response["message"]:
            res = search(i["name"], local_invoice)
            if not res:

                params = {"doctype": "Invoice", "name": i["name"]}
                response = cloud_post("press.api.client.get", params=params)
                inv = response["message"]

                if inv["docstatus"] != 0:
                    doc = frappe.new_doc("Go1 FCloud Invoice")
                    doc.invoice_no = i["name"]
                    doc.status = inv["status"]
                    doc.total = inv["total"]
                    if i["type"] == "Subscription":
                        month = datetime.strptime(i["period_start"], "%Y-%m-%d")
                        doc.invoice = month.strftime("%B %Y")
                        doc.invoice_period = calculate_period(
                            i["period_start"], i["period_end"]
                        )
                    else:
                        month = datetime.strptime(i["due_date"], "%Y-%m-%d")
                        doc.invoice = i["type"]

                    if inv["items"]:
                        for j in inv["items"]:
                            doc.append(
                                "site_billing",
                                {
                                    "site": j["document_name"],
                                    "description": (
                                        j["description"]
                                        if "description" in j.keys()
                                        else ""
                                    ),
                                    "quantity": j["quantity"],
                                    "rate": j["rate"],
                                    "amount": j["amount"],
                                    "period_start": inv["period_start"],
                                    "period_end": inv["period_end"],
                                },
                            )
                        doc.save()
        return
    except Exception:
        frappe.log_error("fcloud_integration.invoice_sync", frappe.get_traceback())


def calculate_period(start_date, end_date):
    start_period = datetime.strptime(start_date, "%Y-%m-%d")
    end_period = datetime.strptime(end_date, "%Y-%m-%d")
    st_year = start_period.year
    st_month = start_period.month
    st_day = start_period.day
    end_year = end_period.year
    end_month = end_period.month
    end_day = end_period.day
    new_start_date = start_period.replace(year=st_year, month=st_month, day=st_day)
    new_end_date = end_period.replace(year=end_year, month=end_month, day=end_day)
    return f"{new_start_date.strftime('%b %d')} - {new_end_date.strftime('%b %d %Y')}"
