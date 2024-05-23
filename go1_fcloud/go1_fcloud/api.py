import frappe
from frappe.model.mapper import get_mapped_doc
@frappe.whitelist()
def new_site(source_name,target_doc=None,ignore_permissions = False):
    doclist = get_mapped_doc(
        "Go1 FCloud Bench",
        source_name,{
            "Go1 FCloud Bench":{
                "doctype":"Go1 FCloud Site"
            }
        },target_doc,ignore_permissions=ignore_permissions
    )
    doclist.status=""
    # doclist.apps=""
    return doclist

@frappe.whitelist()
def new_bench_from_server(source_name,target_doc=None,ignore_permissions = False):
    doclist = get_mapped_doc(
        "Go1 FCloud Server",
        source_name,{
            "Go1 FCloud Server":{
                "doctype":"Go1 FCloud Bench"
            }
        }
    )
    doclist.status = ""
    return doclist

@frappe.whitelist()
def create_bench_for_project(source_name,target_doc=None,ignore_permissions = False):
    doclist = get_mapped_doc(
        "Project",
        source_name,{
            "Project":{
                "doctype":"Go1 FCloud Bench"
            }
        },target_doc,ignore_permissions=ignore_permissions
    )
    # frappe.log_error("src",source_name)
    # doclist.project = args["project"]
    # doclist.apps=""
    return doclist