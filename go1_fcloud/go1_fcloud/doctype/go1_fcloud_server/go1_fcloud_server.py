# Copyright (c) 2024, Tridots Tech and contributors
# For license information, please see license.txt

import frappe,requests
from frappe.model.document import Document

class Go1FCloudServer(Document):
	pass

@frappe.whitelist()
def sync_server_enqueue():
	try:
		frappe.enqueue(sync_server, queue="long")
	except:
		frappe.log_error("sync server enqueue error",frappe.get_traceback())

def sync_server():
	try:
		data = make_request(url = "https://frappecloud.com/api/method/press.api.server.all",method="GET")
		local_server = frappe.get_all('Go1 FCloud Server',fields=["*"])	
		def search(name,local_list):
			return ["found" for server in local_list if server["server_name"] == name]
		for i in data['message']:
			res = search(i["title"],local_server)
			if not res:
				server_doc = frappe.new_doc("Go1 FCloud Server")
				server_doc.status = i["status"]
				server_doc.region = i["cluster"]
				server_doc.price = i["plan"]["price_inr"]
				server_doc.server_name = i["title"]
				server_doc.server_id = i["name"]
				server_doc.vcpu = i["plan"]["vcpu"]
				server_doc.memory = i["plan"]["memory"]
				server_doc.disk = i["plan"]["disk"]
				server_doc.insert(ignore_permissions = True)
	except Exception:
		frappe.log_error("Sync Server Error",frappe.get_traceback())
      
                  
				
def make_request(url, method='GET', params=None,headers=None):
    token, team_id = get_token()
    headers = {"Authorization": token, "X-Press-Team": team_id}
    if method.upper() == 'GET':
        response = requests.get(url=url, headers=headers, params=params)
        # frappe.log_error("headers",headers)
        # frappe.log_error("Get response code",response.status_code)
    elif method.upper() == 'POST':
        response = requests.post(url=url, headers=headers, json=params)
        # frappe.log_error("headers",headers)
        # frappe.log_error("Post response code",response.status_code)
    return response.json()
def get_token():
    try:
        userid = frappe.session.user
        # id = frappe.db.get_value("FCloud Configuration", {'user': userid},"name")       
        user = frappe.get_doc('Go1 FCloud Configuration')
        # frappe.log_error("fcloud config",user.api_key)
        secret = user.get_password("api_secret")
        # frappe.log_error("fcloud config",secret)
        # frappe.log_error("user found",user)
        secret = frappe.get_doc('Go1 FCloud Configuration').get_password('api_secret')
        # frappe.log_error("api secret",secret)
        return f'token {user.api_key}:{secret}', user.x_press_team_id
    except Exception:
        frappe.log_error("get_token_outer error",frappe.get_traceback())