frappe.query_reports["Site Billing Report"] = {
	"filters": [
		{
			'fieldname':'from_date',
			'label':'From Date',
			'fieldtype':'Date'
		},
		{
			'fieldname':'to_date',
			'label':'To Date',
			'fieldtype':'Date'
		},
		{
			'fieldname':'site_name',	
			'label':'Site name',
			'fieldtype':'Data',
		},
		{
			'fieldname':'plan',
			'label':'Plan',
			'fieldtype':'Data',
		}
	]
}
