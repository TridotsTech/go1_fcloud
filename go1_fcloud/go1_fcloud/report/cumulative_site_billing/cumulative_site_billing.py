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
		
		data=frappe.db.get_all("Go1 FCloud Site Billing",fields=["site","description","quantity","rate","amount","period_start","period_end"])
		# frappe.log_error("update invoice",invoices)
		# data=[]
		# for j in invoices:
		# 	data.append({'site':j['site_name'],'description':j['description'] if "description" in j.keys() else "",
		# 		'quantity':j['quantity'],'rate':j['rate'],'amount':j['amount'],
		# 		'period_start':j['period_start'],'period_end':j['period_end']})
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


