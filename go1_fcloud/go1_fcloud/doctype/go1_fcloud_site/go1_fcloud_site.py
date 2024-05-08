# Copyright (c) 2024, Raino and contributors
# For license information, please see license.txt

import frappe
import json
import requests
from frappe.model.document import Document


class Go1FCloudSite(Document):
	@frappe.whitelist()
	def get_token(self):
		try:
		#FCloud User Configuratin Setup....
		# userid = frappe.session.user
		# id = frappe.db.get_value("FCloud User Configuration", {'user': userid},"name")  
		# user = frappe.db.get_value('FCloud User Configuration', id, ['api_key', 'x_press_team_id'])
		# if user[0]:
		# 	frappe.log_error("user found",user)
		# 	secret = frappe.get_doc('FCloud User Configuration', id).get_password('api_secret')
		# 	return f'token {user[0]}:{secret}', user[1]
		# else:
		# 	team = frappe.db.get_value("FCloud User Configuration",id,"team")
		# 	frappe.log_error("user team",team)
		# 	id = frappe.db.get_value("FCloud User Configuration", {'user': team},"name")       
		# 	user = frappe.db.get_value('FCloud User Configuration', id, ['api_key', 'x_press_team_id'])
		# 	secret = frappe.get_doc('FCloud User Configuration', id).get_password('api_secret')
		# 	return f'token {user[0]}:{secret}', user[1]

			# FCloud Configuration Setup
			userid = frappe.session.user
			user = frappe.get_doc('Go1 FCloud Configuration')
			# frappe.log_error("fcloud config",user.api_key)
			secret = user.get_password("api_secret")
			# frappe.log_error("fcloud config",secret)
			# frappe.log_error("user found",user)
			secret = frappe.get_doc('Go1 FCloud Configuration').get_password('api_secret')
			return f'token {user.api_key}:{secret}', user.x_press_team_id
		except Exception:
			frappe.log_error("Get Token Error",frappe.get_traceback())
	
	def make_request(self, url, method='GET', params=None):
		try:
			token, team_id = self.get_token()
			headers = {"Authorization": token, "X-Press-Team": team_id}
			# frappe.log_error("site header",headers)
			if method.upper() == 'GET':
				response = requests.get(url=url, headers=headers, json=params)
				# frappe.log_error("post status code",response.status_code)
			elif method.upper() == 'POST':
				# return type(params)
				response = requests.post(url=url, headers=headers, json=params)
				# frappe.log_error("post status code",response.status_code)
			return response.json()
		except Exception:
			frappe.log_error("Make Request Error",frappe.get_traceback())

	@frappe.whitelist()
	def get_options_for_site(self):
		try:
			url = "https://frappecloud.com/api/method/press.api.site.options_for_new"
			return self.make_request(url)
		except:
			frappe.log_error("Get Options For Site",frappe.get_traceback())
	
	#list apps installed in bench
	@frappe.whitelist()
	def get_apps(self,args):
		try:
			param = {"name": args.name}
			url = "https://frappecloud.com/api/method/press.api.bench.apps"
			return self.make_request(url, params=param)
		except Exception:
			frappe.log_error("Get Apps Error",frappe.get_traceback())
	
	# @frappe.whitelist()
	# def create_site(self,args):
	# 	try:
	# 		# apps = self.get("apps")
	# 		# app_params = [f"{app.title}" for app in apps]
	# 		param = {
	# 				"name": args.name,
	# 				"apps": [
	# 							"erpnext"
	# 						],
	# 				"group": args.group,
	# 				"cluster": args.cluster,
	# 				"plan": args.plan
	# 		}
	# 		params1 = {"site":json.dumps(param)}
	# 		# params = json.loads(params1)
	# 		# return params
	# 		url = "https://frappecloud.com/api/method/press.api.site.new"
	# 		return self.make_request(url, method="POST", params=params1)
	# 	except Exception:
	# 		frappe.log_error("Error creating site", frappe.get_traceback())


#jaffar

	

	@frappe.whitelist()
	def create_site(self,args):
		try:
			
			apps=['frappe']
			new_apps = args.apps
			frappe.log_error("all apps",new_apps)
			frappe.log_error("Sub domain Name",args.name)
			for app in new_apps:
				# frappe.log_error("app name",app)
				apps.append(app['title'])
			if args.bench:
				param = {
					'site':{
						"name": args.name,
						"apps": apps,
						"group": args.group,
						"cluster": args.cluster,
						"plan": args.plan,
						'Subdomain':args.name
					}	
				}
			else:
				#create site on shared bench
				param = {
					'site':{
						"name": args.name,
						"apps": apps,
						"group": args.group,
						"cluster": args.cluster,
						"plan": args.plan,
					}	
				}
			# frappe.log_error("new site param",param)
			response=self.make_request(url ="https://frappecloud.com/api/method/press.api.site.new",
							params=param,method="POST")
			# frappe.log_error("create site response",response)
			return response
		except Exception:
			frappe.log_error("Create Site Error",frappe.get_traceback())

	frappe.whitelist()
	def create_site_enqueue(self,args):
		frappe.enqueue(self.create_site(), queue = "short",args=args)

	@frappe.whitelist()
	def drop_site(self):
		try:
			params = {"name":self.url,'force':'force'}
			frappe.log_error("drop doc name",self.name)
			url = "https://frappecloud.com/api/method/press.api.site.archive"
			response = self.make_request(url,method="POST" ,params=params)
			frappe.log_error('drop site json',response)
			if response == "":
				doc = frappe.get_doc("Go1 FCloud Site",self.name)
				doc.is_dropped=1
				doc.save(ignore_permissions = True)
			return response
		except Exception:
			frappe.log_error("Drop Site Error",frappe.get_traceback())

	@frappe.whitelist()
	def backup_site(self):
		try:
			params = {"name":self.url}
			url = "https://frappecloud.com/api/method/press.api.site.backups"
			response = self.make_request(url,method="POST" ,params=params)
			frappe.log_error('backup site json',response)
			return response
		except Exception:
			frappe.log_error("Backup Site Error",frappe.get_traceback())

	@frappe.whitelist()
	def admin_login(self):
		try:
			params = {"name":self.url}
			url = "https://frappecloud.com/api/method/press.api.site.login"
			admin_response = self.make_request(url,method="POST",params=params)
			return admin_response
		except Exception:
			frappe.log_error("Admin Login Error",frappe.get_traceback())
	@frappe.whitelist()
	def activate_site(self):
		try:
			param={"name":self.url}
			url = "https://frappecloud.com/api/method/press.api.site.activate"
			response = self.make_request(url =url,method="POST",params=param)
			# frappe.log_error("activate response",response)
			return response
		except Exception:
			frappe.log_error("Activate Site Error",frappe.get_traceback())
	@frappe.whitelist()
	def deactivate_site(self):
		try:
			param={"name":self.url}
			url = "https://frappecloud.com/api/method/press.api.site.deactivate"
			response = self.make_request(url = url,method="POST",params=param)
			# frappe.log_error("deactivate response",response)
			return response
		except Exception:
			frappe.log_error("Deactivate Site Error",frappe.get_traceback())
	@frappe.whitelist()
	def schedule_backup(self):
		try:
			params={"name":self.url,"with_files":True}
			url = "https://frappecloud.com/api/method/press.api.site.backup"
			response = self.make_request(url = url,method="POST",params=params)
			# frappe.log_error("schedule backup response",response)
			return response
		except Exception:
			frappe.log_error("Schedule Backup Error",frappe.get_traceback())
	@frappe.whitelist()
	def setup_wizard_complete(self):
		params={
			"name":self.url
		}
		url = "https://frappecloud.com/api/method/press.api.site.setup_wizard_complete"
		response = self.make_request(url=url,params=params,method="POST")
		# frappe.log_error("is_wizard_comlpete",response)
		return response
	##Bench
	@frappe.whitelist()
	def get_bench_list(self):
		url = "https://frappecloud.com/api/method/press.api.bench.all"
		return self.make_request(url)

	@frappe.whitelist()
	def get_status(self,args):
		try:
			res_data=[{"site_app":[],"bench_app":[]}]
			params={
				"name":args.title
			}
			url="https://frappecloud.com/api/method/press.api.site.get"
			response = self.make_request(url = url,method="POST",params=params)
			if("message" in response): #If Site is Active 
				res_data.append({"status":response["message"]["status"]})
			else:#Else attaching archived with site name to get status
				params={
					"name":args.title+".archived"
				}
				url="https://frappecloud.com/api/method/press.api.site.get"
				response = self.make_request(url = url,method="POST",params=params)
				res_data.append({"status":response["message"]["status"]})
			app_response = self.make_request(url="https://frappecloud.com/api/method/press.api.site.installed_apps",
									params=params,method="POST")
			for i in app_response["message"]:
				res_data[0]["site_app"].append({"name":i["app"],"repo":i["repository"]})
			if args.bench:
				bench_res = self.make_request(url="https://frappecloud.com/api/method/press.api.bench.apps",
										method="POST",params={"name":args.group})
				if bench_res:
					for s in bench_res['message']:
						res_data[0]["bench_app"].append({"name":s["name"]})
			# frappe.log_error("sitebefore bench",res_data)
			
			# frappe.log_error("site status",res_data)
			return res_data
		except Exception:
			frappe.log_error("Get Status Error",frappe.get_traceback())
	
	#Returns installed app on sites
	@frappe.whitelist()
	def get_site_apps(self,args):
		res_data=[]
		params={
			"name":args.title
		}
		url="https://frappecloud.com/api/method/press.api.site.installed_apps"
		response=self.make_request(url=url,params=params,method="POST")
		# res_data.append(response)
		# frappe.log_error("site status",response)
		return response

	@frappe.whitelist()
	def get_bench_name(self,args):
		try:
			params={
				"name":args.title
			}
			url = "https://frappecloud.com/api/method/press.api.bench.get"
			response = self.make_request(url = url,params=params,method="POST")
			return response
		except Exception:
			frappe.log_error("get_bench_name",frappe.get_traceback())
	
	@frappe.whitelist()
	def available_custom_apps(self,args):
		try:	
			params={
				"name":args.url
			}
			response = self.make_request(url="https://frappecloud.com/api/method/press.api.site.available_apps",params=params,method="POST")
			return response
		except Exception:
			frappe.log_error("Available Custom App",frappe.get_traceback())
	
	@frappe.whitelist()
	def install_app_on_site(self,args):
		try:
			params={
				"name":args.title,
				"app":args.app
			}
			response=self.make_request(url="https://frappecloud.com/api/method/press.api.site.install_app",params=params,method="POST")
			return response
		except Exception:
			frappe.log_error("install app on site error",frappe.get_traceback())
	
	@frappe.whitelist()
	def migrate(self,args):
		try:
			params={
				"name":args.id
			}
			response = self.make_request(url="https://frappecloud.com/api/method/press.api.site.migrate",params=params,method="POST")
			# frappe.log_error("migrate response",response)
			return response
		except Exception:
			frappe.log_error("Site Migrate Error",frappe.get_tracback())
	
	# @frappe.whitelist()
	# def bench_restart(self,args):
	# 	bench_id=self.make_request(url="https://frappecloud.com/api/method/press.api.site.get",params={"name":args.title},
	# 						 method="POST")
	# 	frappe.log_error("id",bench_id["message"]["group"])
	# 	name = bench_id["message"]["group"]
	# 	# bench_params={"name":args.title};url="https://frappecloud.com/api/method/press.api.bench.restart"
	# 	bench = self.make_request(url="https://frappecloud.com/api/method/press.api.bench.versions",params={"name":name},
	# 								method="POST")
	# 	bench_server_id=bench["message"][0].get("name")
	# 	frappe.log_error("bench id",bench_server_id)
	# 	response = self.make_request(url="https://frappecloud.com/api/method/press.api.bench.restart",params={"name":bench_server_id},
	# 						   method="POST")
	# 	return response

	@frappe.whitelist()
	def get_permission(self):
		try:
			url ="https://frappecloud.com/api/method/press.api.account.get"
			response=self.make_request(url=url,method="POST")
			# frappe.log_error("perm response",response)
			return response
		except Exception:
			frappe.log_error("get_permission exception",frappe.get_traceback())
	
	@frappe.whitelist()
	def get_all_site(self):
		try:
			response = self.make_request(url="https://frappecloud.com/api/method/press.api.site.all",method="POST")
			# frappe.log_error("get all site",response)
			return response
		except Exception:
			frappe.log_error("get all site error",frappe.get_traceback())	
	#Installed apps on bench
	@frappe.whitelist()
	def get_installed_apps(self,args):
		try:
			params={
				"name":args.title
			}
			response=self.make_request(url = "https://frappecloud.com/api/method/press.api.bench.apps",params=params,method="POST")
			return response["message"]
		except Exception:
			frappe.log_error("Get Installed Apps",frappe.get_traceback())

	@frappe.whitelist()
	def remove_app(self,args):
		try:
			params={"app":args.app,"name":args.name}
			response=self.make_request(url="https://frappecloud.com/api/method/press.api.site.uninstall_app",
								
								params=params,method="POST")
			# frappe.log_error("uninstall response",response)
			# frappe.log_error("uninstall params",params)
			return response
		except Exception:
			frappe.log_error("Remove App Error",frappe.get_traceback())
	
	#Restore Database
	@frappe.whitelist()
	def restore_site(self,args):
		try:
			params={
				"url":args.from_site_url,
				"email":args.from_site_username,
				"password":args.password
			}
			# frappe.log_error("restore params",params)
			remote_files=self.make_request(url="https://frappecloud.com/api/method/press.api.site.get_backup_links",
								method="POST",params=params)
			# frappe.log_error("remote files",remote_files)
			arr_files = remote_files["message"]
			db,pub,pri,config="","","",""
			for i in arr_files:
				if i["type"] =="database":
					db=i["remote_file"]
				elif i["type"]=="public":
					pub=i["remote_file"]
				elif i["type"] == "private":
					pri=i["remote_file"]
				else:
					config=i["remote_file"]
			files={
				"database":db,
				"public":pub,
				"private":pri
				# "config":config
			}
			restore_params={
				"name":args.restore_site_url,
				"files":files
			}
			url="https://frappecloud.com/api/method/press.api.site.restore"
			response=self.make_request(url,params=restore_params,method="POST")
			# frappe.log_error("restore response",response)
			return response
		except Exception:
			frappe.log_error("restore site error",frappe.get_traceback())

	# @frappe.whitelist()
	# def get_installed_apps(self,args):
	# 	try:
	# 		params={
	# 			"name":args.title
	# 		}
	# 		response=self.make_request(url = "https://frappecloud.com/api/method/press.api.bench.apps",params=params,method="POST")
	# 		return response["message"]
	# 	except Exception:
	# 		frappe.log_error("get_installed_apps",frappe.get_traceback())

	@frappe.whitelist()
	def get_site_jobs(self,args):
		try:
			params={
				"doctype": "Agent Job",
				"filters": {
					"site": args.id
				},
				"order_by": "creation desc",
				"start": 0,
				"limit": 5,
				"limit_start": 0,
				"limit_page_length": 5,
				"debug": 0
			}
			response=self.make_request(url="https://frappecloud.com/api/method/press.api.site.jobs",params=params,
										method="POST")
			return response
		except Exception:
			frappe.log_error("Get Site Jobs Error",frappe.get_traceback())

	@frappe.whitelist()
	def get_site_plans(self,args):
		try:
			response = self.make_request(url = "https://frappecloud.com/api/method/press.api.site.get_site_plans",
								method= "GET")
			return response
		except Exception:
			frappe.log_error("get site plan",frappe.get_traceback())

	@frappe.whitelist()
	def site_exists(self):
		try:
			if not self.url:
				roles = frappe.get_roles(frappe.session.user)
				params={"domain":"frappe.cloud","subdomain":self.site_name}
				response = self.make_request(url="https://frappecloud.com/api/method/press.api.site.exists",
								method="POST",params = params)
				# frappe.log_error("available",response)
				# frappe.log_error("available type",type(response["message"]))
				return response
		except Exception:
			frappe.log_error("site exists error",frappe.get_traceback())

	@frappe.whitelist()
	def get_new_site_options(self,args=None):
		try:
			response = self.make_request(url = "https://frappecloud.com/api/method/press.api.site.get_new_site_options",
								method="POST")
			# frappe.log_error("new site options",response)
			return response["message"]
		except Exception:
			frappe.log_error("new site optinos error",frappe.get_traceback())
			


# @frappe.whitelist()
def sync_site():
	try:
		import json
		data = make_request(url='https://frappecloud.com/api/method/press.api.site.all',method='POST')
		cloud_site = data['message']
		local_site = frappe.get_all('Go1 FCloud Site',filters={'is_dropped':0},fields=["*"])
		site_options = cloud_site_options()
		# frappe.log_error("cloud site",data)
		# frappe.log_error("cloud site options",site_options)
		def search(name,local_list):
			return ["found" for site in local_list if site["url"] == name]
		for i in cloud_site:
			# frappe.log_error("c site",i)
			# frappe.log_error("site _name",local_site)
			# frappe.log_error('plan',i['plan']['name']+" - INR "+str(int(i['plan']['price_inr'])))
			res = search(i['name'],local_site)
			# frappe.log_error("result",res)
			if not res:
				# frappe.log_error("creating site doc",i)
				cloud_doc = frappe.new_doc("Go1 FCloud Site")
				site_name = i['name'].partition(".")
				cloud_doc.site_name = site_name[0]
				cloud_doc.status = i['status']
				cloud_doc.region = i['cluster']
				cloud_doc.version = i['version']
				cloud_doc.url = i['name']
				cloud_doc.plans = json.dumps(site_options[0]['site_plan'])
				cloud_doc.plan = i['plan']['name']+" - INR "+str(int(i['plan']['price_inr']))
				cloud_doc.bench_data = json.dumps(site_options[0]['bench_list'])
				cloud_doc.site_data = json.dumps(site_options[0]['site_data'])
				cloud_doc.group = i['group']
				
				if i['title'] != i['version']:
					id = frappe.db.get_value('Go1 FCloud Bench',{'bench':i['title']},'name')
					cloud_doc.bench_name = id
					status = get_bench_status(i['group'])
					cloud_doc.bench = i['title']
					cloud_doc.bench_status = status
					site_apps = cloud_site_apps(i['name'],i['group'])
					for i in site_apps[0]['bench_apps']:
						cloud_doc.append('installed',{
							'app_name':i['name']
						})
					for i in site_apps[1]['site_apps']:
						cloud_doc.append('custom',{
						'app_name':i['app'],
						'title':i['repository']
					})
				else:
					# cloud_doc.group = i['group']
					cloud_doc.new_apps = json.dumps(site_options[0]['shared_options'])
					site_apps = cloud_site_apps(i['name'])
					for i in site_apps[0]['site_apps']:
						cloud_doc.append('custom',{
						'app_name':i['repository'],
						'title':i['name']
					})		
				cloud_doc.insert(ignore_permissions = True)   
	except Exception:
		frappe.log_error('sync site error',frappe.get_traceback())

@frappe.whitelist()
def sync_site_enqueue():
	try:
		frappe.enqueue(sync_site(),queue = 'short')
	except Exception:
		frappe.log_error("sync site enqueue error",frappe.get_traceback())

def make_request(url, method=None, params=None,headers=None):
    token, team_id = get_token()
    # frappe.log_error('Cred',[token,team_id])
    headers = {"Authorization": token, "X-Press-Team": team_id}

    if method.upper() == 'GET':
        response = requests.get(url=url, headers=headers, params=params)
        # frappe.log_error("Get response code",response.status_code)
    elif method.upper() == 'POST':
        response = requests.post(url=url, headers=headers, json=params)
        # frappe.log_error("Post response code",response.status_code)
        # frappe.log_error("post json",response.json())
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

def cloud_site_options(bench_id = None):
	site_options = []
	response = make_request(url = "https://frappecloud.com/api/method/press.api.site.get_site_plans",
								 method= "GET")
	shared_site_options = make_request(url="https://frappecloud.com/api/method/press.api.site.get_new_site_options",method="POST")
	site_data = make_request(url='https://frappecloud.com/api/method/press.api.site.options_for_new',method='GET')
	bench_list = make_request(url="https://frappecloud.com/api/method/press.api.bench.all",method = "GET")
	site_options.append({'site_plan':response['message'],'shared_options':shared_site_options['message'],
					  'bench_list':bench_list['message'],'site_data':site_data['message']})
	return site_options
	
def get_bench_status(bench_id):
	bench_response = make_request(url = "https://frappecloud.com/api/method/press.api.bench.get",
							   params={'name':bench_id},method='POST')
	status = bench_response['message']['status']
	# frappe.log_error('bench status',status)
	return status
def cloud_site_apps(site_url,bench_id=None):
	apps = []
	if bench_id:
		bench_apps = make_request(url = "https://frappecloud.com/api/method/press.api.bench.apps",params={"name":bench_id},
							method="POST")
		apps.append({'bench_apps':bench_apps["message"]})
	site_apps = make_request(url="https://frappecloud.com/api/method/press.api.site.installed_apps",params={'name':site_url},
						  method="POST")
	apps.append({'site_apps':site_apps['message']})
	return apps
# def get_key(file):
# 	token, team_id = get_token()
# 	headers = {"Authorization": token, "X-Press-Team": team_id}
# 	params={"file":file}
# 	response=requests.get(url="https://frappecloud.com/api/method/press.api.site.get_upload_link",headers=headers,params=params)
# 	return response.json()

# def backup_info(files,args):
# 	token, team_id = get_token()
# 	headers = {"Authorization": token, "X-Press-Team": team_id}
# 	paths = get_path(files)
# 	frappe.log_error("paths",paths)
# 	db_params={
# 		"file":args[0],
# 		"path":paths[0],
# 		"size":args[6],
# 		"type":"application/x-gzip"
# 	}
# 	public_params={
# 		"file":args[2],
# 		"path":paths[2],
# 		"size":args[7],
# 		"type":"application/x-tar"
# 	}
# 	private_params={
# 		"file":args[1],
# 		"path":paths[1],
# 		"size":args[8],
# 		"type":"application/x-tar"
# 	}
# 	frappe.log_error("db_params",db_params)
# 	frappe.log_error("public_params",public_params)
# 	frappe.log_error("private_params",private_params)
# 	db_id=requests.post(url="https://frappecloud.com/api/method/press.api.site.uploaded_backup_info",headers=headers,params=db_params)
# 	frappe.log_error("db_id response",db_id.status_code)
# 	pb_id=requests.post(url="https://frappecloud.com/api/method/press.api.site.uploaded_backup_info",headers=headers,params=public_params)
# 	frappe.log_error("db_id response",pb_id.status_code)
# 	pr_id=requests.post(url="https://frappecloud.com/api/method/press.api.site.uploaded_backup_info",headers=headers,params=private_params)
# 	frappe.log_error("db_id response",pr_id.status_code)
# 	frappe.log_error("db_file",db_id)
# 	frappe.log_error("pb_id",pb_id)
# 	frappe.log_error("pr_id",pr_id)
# 	db=db_id.json()
# 	pb=pb_id.json()
# 	pr=pr_id.json()
# 	return [db['message'],pb['message'],pr['message']]

# def get_path(files):
# 	database_path=get_key(files["database"])
# 	public_path=get_key(files["public"])
# 	private_path=get_key(files["private"])
# 	db_key=database_path.get("message")
# 	pub_key=public_path.get("message")
# 	pri_key=private_path.get("message")
# 	db_path = db_key['fields'].get("key")
# 	pub_path=pub_key['fields'].get("key")
# 	pri_path=pri_key['fields'].get("key")
# 	# frappe.log_error("keys",[db_path,pub_path,pri_path])
# 	return [db_path,pub_path,pri_path]

# def get_upload_backup():
# 	token, team_id = get_token()
# 	headers = {"Authorization": token, "X-Press-Team": team_id}
