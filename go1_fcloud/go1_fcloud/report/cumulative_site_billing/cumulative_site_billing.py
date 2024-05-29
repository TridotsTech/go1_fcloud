# Copyright (c) 2024, Tridots Tech and contributors
# For license information, please see license.txt

import frappe,requests


def execute(filters=None):
	columns, data = get_column(), get_data(filters)
  
	return columns, data

def get_column():
      return[{
                'label':'Site',
                'fieldname':'site',
                'fieldtype':'Data',
                'width':'250'
			},{
				'label':'Description',
                'fieldname':'description',
                'fieldtype':'Data',
                'width':'500'
			},{
                'label':'Quantity (in Days)',
                'fieldname':'quantity',
                'fieltype':'Float',
                'width':'150'
			},{
                'label':'Rate',
                'fieldname':'rate',
                'fieltype':'Float',
                'width':'100'
			},{
                'label':'Amount',
                'fieldname':'amount',
                'fieltype':'Float',
                'width':'200'
			},{
				'label':'Period Start',
				'fieldname':'period_start',
				'fieldtype':'Date',
				'width':'200'
			},{
				'label':'Period End',
				'fieldname':'period_end',
				'fieldtype':'Date',
				'width':'200'
			}]
def get_data(filters):
	try:
		token,team_id = get_token()
		headers = {"Authorization": token, "X-Press-Team": team_id}
		total_params ={"doctype":"Invoice","fields":["name","type","invoice_pdf","payment_mode","stripe_invoice_url","name","status","due_date","total","amount_paid","amount_due",],"filters":{},"order_by":"due_date desc","start":0,"limit":20,"limit_start":0,"limit_page_length":20,"debug":0}
		invoices_response =requests.post(url = "https://frappecloud.com/api/method/press.api.client.get_list",headers=headers,
										params=total_params).json()
		data=[]
		# frappe.log_error("inv res",invoices_response)
		for i in invoices_response['message']:
			params={"doctype":"Invoice","name":i['name']}
			response = requests.post(url = "https://frappecloud.com/api/method/press.api.client.get",
							params=params,headers=headers).json()
			items = response['message']
			for j in items['items']:
				data.append({'site':j['document_name'],'description':j['description'] if "description" in j.keys() else "",
				 'quantity':j['quantity'],'rate':j['rate'],'amount':j['amount'],
				 'period_start':items['period_start'],'period_end':items['period_end']})
		# frappe.log_error("invoices",data)
		if filters.get("site"):
			data = filter_data_in(data,"site",filters.get("site").lower())

		return data
	except Exception:
		frappe.log_error("go1 fcloud.cumulative",frappe.get_traceback())

def filter_data_in(data,field,value):
	output = []
	for i in data:
		if value in i[field].lower():
			output.append(i)
	return output

def get_token():
        try: 
            user = frappe.get_doc('Go1 FCloud Configuration')
            secret = user.get_password("api_secret")
            secret = frappe.get_doc('Go1 FCloud Configuration').get_password('api_secret')
            return f'token {user.api_key}:{secret}', user.x_press_team_id
        except Exception:
            frappe.log_error("Get Token Error",frappe.get_traceback())

