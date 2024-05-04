import frappe
import requests
import datetime

def execute(filters=None):
    if not filters:filters={}
    columns=get_column()
    cs_data=get_cs_data(filters)

    if not cs_data:
        frappe.msgprint('No records Found')
        return columns , cs_data

    data=[]

    # frappe.log_error("cs data",cs_data)

    for d in cs_data:
        row=frappe._dict({
            "site_name":d["site_name"],
            "created":d["creation"],
            "plan":d["plan"],
            "rate":d["rate"],
            "quantity":d["quantity"],
            "amount":d["amount"]
        })
        # frappe.log_error("type",type(d["creation"]))
        data.append(row)

    return columns,data

def get_column():
    return[{
        'fieldname':'site_name',
		'label':'Site Name',
		'fieldtype':'Data',
		'width':'350'
    },{
        'fieldname':"created",
        'label':'Creation Date',
        'fieldtype':'Date',
        'width':'250'
    },
    {
		'fieldname':'plan',
		'label':'Plan',
		'fieldtype':'Data',
        'width':'150'
	},
    {
        'fieldname':'rate',
		'label':'Rate',
		'fieldtype':'Data',
        'width':'150'
    },
    {
        'fieldname':'quantity',
		'label':'Quantity',
		'fieldtype':'Data',
        'width':'150'
    },
    {
        'fieldname':'amount',
		'label':'Amount',
		'fieldtype':'Data',
        'width':'150'
    }]

def get_cs_data(filters):
    # conditions=get_conditions(filters)
    token, team_id = get_token()
        # frappe.log_error('Cred',[token,team_id])
    headers = {"Authorization": token, "X-Press-Team": team_id}
    # headers = {'Authorization': 'Token 79ae58c9d806eab16761efeea01b9db2b7dd0adbf372c97dbe06a89f:e06b6f82e28a58b5eec2aee060954af73dab546fb4e3f7e196498a91',
    #             'X-Press-Team': 'c7ca87112b'}
    message=requests.post(url="https://frappecloud.com/api/method/press.api.billing.upcoming_invoice",headers=headers).json()
    response = message["message"]
    data = response["upcoming_invoice"]
    items = data["items"]
    # frappe.log_error("data response",items)
    data = []
    # for i in items:
    #     frappe.log_error("i",i["document_name"])
    #     doc = {"name":i["document_name"],"creation":i["creation"],"plan":i["plan"],"quantity":i["quantity"],"rate":i["rate"],"amount":i["amount"]}
    #     data.append(doc)
    for i in items:
        doc = {"site_name":i["document_name"],"creation":i["creation"],"plan":i["plan"],"quantity":i["quantity"],"rate":i["rate"],"amount":i["amount"]}
        data.append(doc)
    
    if filters.get("site_name"):
        data = filter_data_in(data, "site_name", filters.get("site_name").lower())
    if filters.get("plan"):
        data = filter_data_in(data, "plan", filters.get("plan").lower())
    if filters.get("from_date"):
        data = filter_date(data, "creation", filters.get("from_date"), ">")
    if filters.get("to_date"):
        data = filter_date(data, "creation", filters.get("to_date"), "<")
    
    # for i in items:
    #     if filters.get("site_name") and not filters.get("plan"):
    #         if filters.get("site_name") in i["document_name"]:
    #             frappe.log_error("i",i["document_name"])
    #             doc = {"name":i["document_name"],"creation":i["creation"],"plan":i["plan"],"quantity":i["quantity"],"rate":i["rate"],"amount":i["amount"]}
    #             data.append(doc)
    #     elif not filters.get("site_name") and filters.get("plan"):
    #         if filters.get("plan") in i["plan"]:
    #             frappe.log_error("i",i["document_name"])
    #             doc = {"name":i["document_name"],"creation":i["creation"],"plan":i["plan"],"quantity":i["quantity"],"rate":i["rate"],"amount":i["amount"]}
    #             data.append(doc)
    #     elif not filters.get("site_name") and not filters.get("plan"):
    #         frappe.log_error("i",i["document_name"])
    #         doc = {"name":i["document_name"],"creation":i["creation"],"plan":i["plan"],"quantity":i["quantity"],"rate":i["rate"],"amount":i["amount"]}
    #         data.append(doc)
    #     elif filters.get("site_name") and filters.get("plan"):
    #         if filters.get("site_name") in i["document_name"]:
    #             if filters.get("plan") in i["plan"]:
    #                 frappe.log_error("i",i["document_name"])
    #                 doc = {"name":i["document_name"],"creation":i["creation"],"plan":i["plan"],"quantity":i["quantity"],"rate":i["rate"],"amount":i["amount"]}
    #                 data.append(doc)
    return data



def filter_data_in(data, field, value):
    output = []
    for i in data:
        if value in i[field].lower():
            output.append(i)
    return output

def filter_date(data, field, value, sign):
    output = []
    for i in data:
        i[field] = i[field].split(" ")[0]
        if sign == ">":
            if datetime.datetime.strptime(i[field], "%Y-%m-%d") >= datetime.datetime.strptime(value, "%Y-%m-%d"):
                output.append(i)
        else:
            if datetime.datetime.strptime(i[field], "%Y-%m-%d") <= datetime.datetime.strptime(value, "%Y-%m-%d"):
                output.append(i)
    return output

def get_token():
        try:
            # userid = frappe.session.user
            # id = frappe.db.get_value("FCloud Configuration", {'user': userid},"name")       
            user = frappe.get_doc('Go1 FCloud Configuration')
            # frappe.log_error("fcloud config",user.api_key)
            secret = user.get_password("api_secret")
            # frappe.log_error("fcloud config",secret)
            # frappe.log_error("user found",user)
            secret = frappe.get_doc('Go1 FCloud Configuration').get_password('api_secret')
            return f'token {user.api_key}:{secret}', user.x_press_team_id
        except Exception:
            frappe.log_error("Get Token Error",frappe.get_traceback())