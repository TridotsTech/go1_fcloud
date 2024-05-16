 # Copyright (c) 2024, Raino and contributors
# For license information, please see license.txt

import frappe
import json
import requests
from frappe.model.document import Document


# class Go1FCloudBench(Document):
# 	@frappe.whitelist()
# 	def get_bench_list(self):
# 		user = frappe.db.get_value('FCloud User Configuration','3e58210b78',['api_key',"x_press_team_id"])
# 		secret = frappe.get_doc('FCloud User Configuration','3e58210b78').get_password('api_secret')
# 		token = f'token {user[0]}:{secret}'
# 		url=f"https://frappecloud.com/api/method/press.api.bench.all"

# 		r = requests.get(url = url, headers = {"Authorization":token, "X-Press-Team": user[1]})
# 		get_data= r.json()
# 		# resData = json.dumps(get_data)
# 		return get_data
	
# 	@frappe.whitelist()
# 	def get_dependencies(self):
# 		user = frappe.db.get_value('FCloud User Configuration','3e58210b78',['api_key',"x_press_team_id"])
# 		secret = frappe.get_doc('FCloud User Configuration','3e58210b78').get_password('api_secret')
# 		token = f'token {user[0]}:{secret}'
# 		bench_param = {"name": self.id}
		           
# 		url=f"https://frappecloud.com/api/method/press.api.bench.dependencies"

# 		r = requests.get(url = url, headers = {"Authorization":token, "X-Press-Team": user[1]},params=bench_param)
# 		get_dependencies= r.json()
# 		return get_dependencies


class Go1FCloudBench(Document):

    def validate_user(self):
        user = frappe.session.user
        roles = frappe.get_roles(user)
        return roles

    def get_token(self):
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
            frappe.log_error("Get Token Error",frappe.get_traceback())
    
    def make_request(self, url, method='GET', params=None,headers=None):
        token, team_id = self.get_token()
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
    

    #To Set bench name in Project
    @frappe.whitelist()
    def set_bench_id(self,args):
        try:
            # frappe.log_error("set bench id args...",args)
            doc = frappe.get_doc("Project",args["project_name"])
            if not doc.custom_bench:
                doc.custom_bench = args["name"]
                doc.save(ignore_permissions = True)
        except Exception:
            frappe.log_error("map bench in project error",frappe.get_traceback())


    @frappe.whitelist()
    def get_bench_options(self):
        try:
            response = self.make_request(url="https://frappecloud.com/api/method/press.api.bench.options",method="POST")
            # frappe.log_error("bench opt resp",response)
            return response
        except Exception:
            frappe.log_error("get_bench_options",frappe.get_traceback())
    
    @frappe.whitelist()
    def create_bench(self,args):
        try:
            benc_apps = []
            for app in args.apps:
                app_dict = {"name":"","source":""}
                app_dict["source"]=app["name1"]
                app_dict["name"]=app["title"]
                benc_apps.append(app_dict)

            param={
                'bench':{
                    "title": args.title,
                    "version": args.version,
                    "cluster": args.region,
                    "server":"",
                    "saas_app":"",
                    "apps":benc_apps
                }	
            }
            # frappe.log_error("bench params",params)
            # try:
            token, team_id = self.get_token()
            headers = {"Authorization": token, "X-Press-Team": team_id}
            # frappe.log_error("headres",headers)
            response = requests.post(url="https://frappecloud.com/api/method/press.api.bench.new",json=param,headers=headers)
            # frappe.log_error("bench status",response.status_code)
            # frappe.log_error("bench resposne",response.json())
            resp = response.json()
            bench_name = {"name":resp["message"]}
            get_bench = requests.post(url="https://frappecloud.com/api/method/press.api.bench.get",json=bench_name,headers=headers)
            return get_bench.json()
        except Exception:
            frappe.log_error("create Bench error",frappe.get_traceback())

    @frappe.whitelist()
    def _deploy_bench(self,args):
        params={
            "name":args.title
        }
        release_response = self.make_request(url="https://frappecloud.com/api/method/press.api.bench.deploy_information",
                                        params=params,method="POST")
        token, team_id = self.get_token()
        headers = {"Authorization": token, "X-Press-Team": team_id}
        rel_msg = release_response["message"]
        # frappe.log_error("update available",rel_msg)
        new_updates=[]
        if rel_msg["update_available"] == True:
            # frappe.log_error("show updates message",rel_msg)
            apps = rel_msg["apps"]
            for app in apps:
                # frappe.log_error("current tag",app)
                names = app["releases"]
                for name in names:
                    if name["name"] == app["next_release"]:
                        update={"title":app["title"],"app":app["app"],"repo":app["repository"],
                                "owner":app["repository_owner"],"branch":app["branch"],
                                "status":name["status"],"tag":name["tag"],"current_tag":app["current_tag"],
                                "next_release":app["next_release"]}
                        new_updates.append(update)
            removed = rel_msg["removed_apps"]
            if removed:
                for r in removed:
                    update={"title":r["title"],"status":"Will Be Uninstalled","tag":"remove"}
                    new_updates.append(update)
            # frappe.log_error("new updates",new_updates)
            return new_updates
            # in_apps = rel_msg["apps"]
            # for i in in_apps:
            #     app = {"app":i["app"],"release":i["next_release"]}
            #     apps.append(app)
            # params={
            #     "name":args.title,
            #     "apps":apps
            # }
            # frappe.log_error("deploy",params)
            # response = requests.post(url="https://frappecloud.com/api/method/press.api.bench.deploy_and_update",json = params,
            #                          headers=headers)
            # frappe.log_error("deploy_response",response.json())
            # return response.json()
        else:
            frappe.throw("Bench Already Deployed")
    
    @frappe.whitelist()
    def deploy_and_update(self,args):
        try:
            apps=[];sites=[]
            token, team_id = self.get_token()
            headers = {"Authorization": token, "X-Press-Team": team_id}
            in_apps=args.message
            # frappe.log_error("in_apps",in_apps)

            # if not in_apps[0]["app"]:
            #     frappe.log_error("not app in_app","no Values")

            for i in in_apps[0]["app"]:
                if "app" in i.keys():
                    app = {"app":i["app"],"release":i["next_release"]}
                    apps.append(app)
                else:
                    apps=[]
            for s in in_apps[0]["site"]:
                # frappe.log_error("S",s)
                sites.append({"name":s["name"],"bench":s["bench"],"server":s["server"],"skip_failing_patches":0,"skip_backups":0})

            params={
                "name":args.title,
                "apps":apps,
                "sites":sites
            }   
            # frappe.log_error("deploy",params)
            
            response = self.make_request(url="https://frappecloud.com/api/method/press.api.bench.deploy_and_update",params = params,
                                    method="POST")
            # frappe.log_error("deploy_response",response)
            return response
        except Exception:
            frappe.log_error("deploy eror",frappe.get_traceback())
    
    @frappe.whitelist()
    def bench_build(self,args):
        try:
            bench_param={"name":args.title}
            bench_version=self.make_request(url="https://frappecloud.com/api/method/press.api.bench.versions",
                                            params=bench_param,method="POST")
            bench = bench_version["message"]
            param={
                "name":bench[0]["name"]
            }
            # frappe.log_error("bench build param",param)
            response=self.make_request(url="https://frappecloud.com/api/method/press.api.bench.rebuild",
                                    params=param,method="POST")
            return response
        except Exception:
            frappe.log_error("Error in Bench Build",frappe.get_traceback())

    # @frappe.whitelist()
    def _get_status(self,args):
        try:
            user = frappe.session.user
            roles = frappe.get_roles(user)
            # frappe.log_error("session roles",roles)
            params = {
                    "name":args.title
            }
            response = self.make_request(url = "https://frappecloud.com/api/method/press.api.bench.get",params=params,method="POST")
            return response
        except Exception:
            frappe.log_error("get status",frappe.get_traceback())
    
    @frappe.whitelist()
    def get_bench_list(self):
        url = "https://frappecloud.com/api/method/press.api.bench.all"
        return self.make_request(url)
    
    @frappe.whitelist()
    def get_certificate(self,args):
        ssh_key = frappe.db.get_single_value("Go1 FCloud Settings","ssh_key")
        # frappe.log_error('ssh key',ssh_key)
        if not ssh_key:
            frappe.throw("Set public key in Go1 FCloud Settings")
        try:
            ssh_param = {
            "key":ssh_key
            }
            ssh_response = self.make_request(url = "https://frappecloud.com/api/method/press.api.account.add_key",params = ssh_param,
                                                method="POST")
            # frappe.log_error("ssh add_key response",ssh_response)
            if "exception" in ssh_response:
                frappe.throw(ssh_response['exception'])
            else:
                params={
                    "name":args.title
                }
                response = self.make_request(url="https://frappecloud.com/api/method/press.api.bench.generate_certificate",params=params,
                                            method="POST")
                # frappe.log_error("response certificate",response)
                frappe.msgprint("Click Get SSH Access to get generated SSH .This certificate will be valid for 6 hours.")
        except Exception:
            frappe.log_error("generate ssh error",frappe.get_traceback())

    @frappe.whitelist()
    def certificate(self,args):
        try:
            params={
                "name":args.title
            }
            response = self.make_request(url="https://frappecloud.com/api/method/press.api.bench.certificate",params=params,
                                            method="POST")
            command = self.make_request(url="https://frappecloud.com/api/method/press.api.bench.versions",params=params,method="POST")
            # frappe.log_error("cert resp",response)
            # frappe.log_error("cmd resp",command)
            if response["message"] == False:
                frappe.throw("Generate Token First and get the token")
            else:
                if "exception" in response or "exception" in command:
                    frappe.throw("No sites available")
                else:
                    res = response["message"];cmd=command["message"]
                    # frappe.log_error("response ssh",response["message"])
                    # frappe.log_error("cmd",cmd[0])
                    if "ssh_certificate" in res:
                        message=[{"certificate":res["ssh_certificate"],"command":"ssh "+cmd[0]["name"]+"@"+cmd[0]['proxy_server']+" -p 2222"}] 
                        return message
                    else:
                        frappe.throw("Try to generate and get access token after 15 or 30 minutes")       
        except Exception:
            frappe.log_error("get ssh key error",frappe.get_traceback())

    @frappe.whitelist()
    def get_installed_apps(self,args):
        try:
            params={
                "name":args.title
            }
            response=self.make_request(url = "https://frappecloud.com/api/method/press.api.bench.apps",params=params,method="POST")
            return response["message"]
        except Exception:
            frappe.log_error("get_installed_apps",frappe.get_traceback())
        
    @frappe.whitelist()
    def versions(self,args):
        try:
            key= list(args.keys())
            # frappe.log_error("Checfk keys",key)
            if "id" in key:
                params={"name":args.id}
            else:
                params={"name":args.title}
            
            version_response = self.make_request(url="https://frappecloud.com/api/method/press.api.bench.versions",params=params,method="POST")
            # frappe.log_error("version response",version_response)
            return version_response
        except Exception:
            frappe.log_error("version error",frappe.get_traceback())
    
    @frappe.whitelist()
    def update_site(self,args):
        try:
            params={"name":args.id}

            response=self.make_request(url="https://frappecloud.com/api/method/press.api.bench.update_all_sites",
                                    params=params,method="POST")
            # frappe.log_error("update site response",response)
            return response
        except Exception:
            frappe.log_error("Update_all_site",frappe.get_traceback())

    @frappe.whitelist()
    def get_git_repo(self):
        try:
            response = self.make_request(url = "https://frappecloud.com/api/method/press.api.github.options",method="POST")
            return response
        except Exception:
            frappe.log_error("Error Validating App",frappe.get_traceback())
    
    
    #Adding Custom App from Github
    @frappe.whitelist()
    def available_app(self,args):
        try:
            params={
                "installation":args.id,
                "name":args.name,
                "owner":args.owner
            }
            response = self.make_request(url="https://frappecloud.com/api/method/press.api.github.repository",
                                params=params,method="POST")
            # frappe.log_error("validate response",response)
            return response
        except Exception:
            frappe.log_error("available app",frappe.get_traceback())

    @frappe.whitelist()
    def validate_app(self,args):
        try:
            params={
                "branch":args.branch,
                "installation":args.install_id,
                "owner":args.owner,
                "repository":args.repo
            }
            response = self.make_request(url="https://frappecloud.com/api/method/press.api.github.app",
                                params=params,method="POST")
            # frappe.log_error("validate app response",response)
            return response
        except Exception:
            # frappe.throw("App not valid")
            frappe.log_error("validate app",frappe.get_traceback())

    @frappe.whitelist()
    def add_custom_app(self,args):
        try:
            token, team_id = self.get_token()
            headers = {"Authorization": token, "X-Press-Team": team_id}
            params={
                "app":{
                    "branch":args.branch,
                    "github_installation_id":args.install_id,
                    "group":args.bench,
                    "name":args.name,
                    "repository_url":args.url,
                    "title":args.title
                }
            }
            # response = requests.post(url="https://frappecloud.com/api/method/press.api.app.new",
            #                     json=params,headers=headers)
            response=self.make_request(url="https://frappecloud.com/api/method/press.api.app.new",params=params,method="POST")
            # frappe.log_error("validate app response",response)
            # frappe.log_error("status code",response)
            return response
        except Exception:
            frappe.log_error("add_custom_app",frappe.get_traceback())

    @frappe.whitelist()
    def bench_restart(self,args):
            try:
        # bench_id=self.make_request(url="https://frappecloud.com/api/method/press.api.site.get",params={"name":args.title},
        #                         method="POST")
        # frappe.log_error("id",bench_id["message"]["group"])
        # name = bench_id["message"]["group"]
        # bench_params={"name":args.title};url="https://frappecloud.com/api/method/press.api.bench.restart"
        
                bench = self.make_request(url="https://frappecloud.com/api/method/press.api.bench.versions",params={"name":args.title},
                                            method="POST")
                # frappe.log_error("bench",bench)
                bench_server_id=bench["message"][0].get("name")
                # frappe.log_error("bench id",bench_server_id)
                response = self.make_request(url="https://frappecloud.com/api/method/press.api.bench.restart",params={"name":bench_server_id},
                                        method="POST")
                return response
            except Exception:
                frappe.log_error("bench restart error",frappe.get_traceback())
        
    
    @frappe.whitelist()
    def get_permission(self):
        try:
            url ="https://frappecloud.com/api/method/press.api.account.get"
            response=self.make_request(url=url,method="POST")
            return response
        except Exception:
            frappe.log_error("get_permission exception",frappe.get_traceback())

    @frappe.whitelist()
    def drop_bench(self,args):
        try:
            params={"name":args.title}
            url="https://frappecloud.com/api/method/press.api.bench.archive"
            response=self.make_request(url=url,params=params,method="POST")
            return response
        except Exception:
            frappe.log_error("Drop bench",frappe.get_traceback())

    @frappe.whitelist()
    def get_all_site(self,args):
        try:
            res_data=[{"jobs":[]},{"deploys":[]}]
            response = self.make_request(url="https://frappecloud.com/api/method/press.api.site.all",method="POST")
            res_data.append(response["message"])
            # frappe.log_error("res data before jobs",res_data)
            params={
                    "doctype": "Agent Job",
                    "filters": {
                        "name": args.title
                    },
                    "order_by": "creation desc",
                    "start": 0,
                    "limit": 10,
                    "limit_start": 0,
                    "limit_page_length": 5,
                    "debug": 0
                }
            dep_params={
                "doctype": "Deploy Candidate",
                "filters": {
                    "group":args.title
                },
                "start": 0,
                "limit": 10,
                "limit_start": 0,
                "limit_page_length": 5,
                "debug": 0
            }
            job_response=self.make_request(url="https://frappecloud.com/api/method/press.api.bench.jobs",params=params,method="POST")
            # frappe.log_error("all site code",response.status_code)
            for i in job_response["message"]:
                # frappe.log_error("i res",i)
                res_data[0]["jobs"].append({"type":i['job_type'],"start":i["start"],"end":i["end"],"status":i["status"]})
            dep_response=self.make_request(url="https://frappecloud.com/api/method/press.api.bench.candidates",params=dep_params,method="POST")
            # frappe.log_error("dep response",dep_response)
            for i in dep_response["message"]:
                # steps=[]
                # job_steps = self.get_candidate(i['name'])
                # jobs=""
                # for j in job_steps:
                #     steps.append({"name":j['stage']+" - "+j["step"],"status":})
                # frappe.log_error("jobs",job_steps)
                res_data[1]["deploys"].append({"name":i["name"],"creation":i["creation"],"status":i["status"],"apps":i["apps"]})
            # frappe.log_error("jobs",res_data[0].jobs)
            return res_data
        except Exception:
            frappe.log_error("get all site",frappe.get_traceback())

    def get_candidate(self,job):
        job_param={"name":job}
        resp = self.make_request(url = "https://frappecloud.com/api/method/press.api.bench.candidate",method="POST",
                                 params=job_param)
        return resp["message"]['build_steps']
    
    @frappe.whitelist()
    def update_app(self,args):
        try:
            # token, team_id = self.get_token()
            # headers = {"Authorization": token, "X-Press-Team": team_id}
            apps=[]
            for i in args.apps:
                # frappe.log_error("i app",i["app"])
                apps.append({"app":i["app"],"source":i["source"]})
            params={"name":args.name,"apps":apps}
            # frappe.log_error("apps",params)
            response = self.make_request(url="https://frappecloud.com/api/method/press.api.bench.add_apps",params=params,
                                    method="POST")
            return response
        except Exception:
            frappe.log_error("update app",frappe.get_traceback())

    @frappe.whitelist()
    def show_installed_apps(self,args):
        try:
            params={"name":args.name}
            response=self.make_request(url="https://frappecloud.com/api/method/press.api.bench.apps",params=params,
                                       method="POST")
            return response
        except Exception:
            frappe.log_error("show install app",frappe.get_traceback())
    
    @frappe.whitelist()
    def remove_app(self,args):
        try:
            params={"name":args.id,"app":args.name}
            response = self.make_request(url="https://frappecloud.com/api/method/press.api.bench.remove_app",
                                        params=params,method="POST")
            # frappe.log_error("remove app response",response)
            return response
        except Exception:
            frappe.log_error("remove app",frappe.get_traceback())

    @frappe.whitelist()
    def get_deploy_site(self,args):
        try:
            params={"name":args.id}
            response=self.make_request(url="https://frappecloud.com/api/method/press.api.site.get",params=params,
                                       method="POST")
            # frappe.log_error("get_site",response)
            return response
        except Exception:
            frappe.log_error("get_site for add app",frappe.get_traceback())
        
    @frappe.whitelist()
    def bench_jobs(self,args):
        try:
            params={
                "doctype": "Agent Job",
                "filters": {
                    "name": args.title
                },
                "order_by": "creation desc",
                "start": 0,
                "limit": 10,
                "limit_start": 0,
                "limit_page_length": 5,
                "debug": 0
            }
            response=self.make_request(url="https://frappecloud.com/api/method/press.api.bench.jobs",params=params,method="POST")
            # frappe.log_error("jobs response",response)
            return response
        except Exception:
            frappe.log_error("job response error",frappe.get_traceback())
    
    @frappe.whitelist()
    def get_site_doc(self,args):
        doc = frappe.db.get_value('Go1 FCloud Site', {'url': args.url}, ['name'])
        return doc
    
    
    @frappe.whitelist()
    def get_status(self,args):
        try:
            all_status = []
            status = self._get_status(args)
            installed_apps = self.get_installed_apps(args)
            get_site = self.get_all_site(args)
            all_status.append({"bench":status})
            all_status.append({"installed_apps":installed_apps})
            all_status.append({"sites":get_site})
            # frappe.log_error("status",all_status)
            return all_status
            
        except Exception:
            frappe.log_error("Get Status Error",frappe.get_traceback())

    @frappe.whitelist()
    def edit_title(self,args):
        
        params = {
            "name":args.name,
            "title":args.title
        }
        url = "https://frappecloud.com/api/method/press.api.bench.rename"
        response = self.make_request(url=url,params=params,method="POST")
        return response
    
    @frappe.whitelist()
    def deploy_bench(self,args):
        try:
            deploys=[]
            deploy_bench = self._deploy_bench(args)
            get_version = self.versions(args)            
            deploys.append({"deploys":deploy_bench});deploys.append({"versions":get_version["message"]})
            # frappe.log_error("deploy bench details",deploys)
            return deploys
        except Exception:
            frappe.log_error("deploy_bench",frappe.get_traceback())

@frappe.whitelist()
def sync_bench():
    try:
        import json
        data = make_request(url="https://frappecloud.com/api/method/press.api.bench.all",
                                        params={"bench_filter":{"status":"All","tag":""}},method="POST")
        cloud_bench = data["message"]
        frappe.log_error("all bench",cloud_bench)
        bench_data= make_request(url = "https://frappecloud.com/api/method/press.api.bench.options",
                                     method="POST")
        local_bench = frappe.get_all("Go1 FCloud Bench",filters={"is_dropped":0},fields=["*"])
        def search(name,local_list):
                return ["found" for bench in local_list if bench["bench"] == name]
        for i in cloud_bench:
    #       cloud_doc = frappe.new_doc("Go1 FCloud Bench")
            res = search(i["title"],local_bench)
            if not res:
                cloud_details = get_cloud_bench_details(i["name"])
                apps =  cloud_details["installed_apps"]
                cloud_doc = frappe.new_doc("Go1 FCloud Bench")
                json_mylist = json.dumps(bench_data["message"], separators=(',', ':'))
                cloud_doc.data = json_mylist
                cloud_doc.bench = i["title"]
                cloud_doc.id = i["name"]
                cloud_doc.status = i["status"]
                cloud_doc.version = i["version"]
                cloud_doc.region = cloud_details["region"]
                for i in apps:
                    cloud_doc.append("apps",{
                        'title':i["name"]
                    })
                    cloud_doc.append("custom",{
                        "title":i["name"],
                        "app_name":i["name"]
                    })
                # frappe.log_error("bench items",i["title"]+":"+i["version"]+str(bench_data["message"]))
                cloud_doc.insert(ignore_permissions = True)   
            # else:
            #     frappe.log_error("working else sync",i['title'])
            #     cloud_details = get_cloud_bench_details(i["name"])
            #     apps =  cloud_details["installed_apps"]
            #     cloud_doc = frappe.get_doc("Go1 FCloud Bench",i['title'])
            #     json_mylist = json.dumps(bench_data["message"], separators=(',', ':'))
            #     cloud_doc.data = json_mylist
            #     cloud_doc.bench = i["title"]
            #     cloud_doc.id = i["name"]
            #     cloud_doc.status = i["status"]
            #     cloud_doc.version = i["version"]
            #     cloud_doc.region = cloud_details["region"]
            #     for i in apps:
            #         cloud_doc.append("apps",{
            #             'title':i["name"]
            #         })
            #         cloud_doc.append("custom",{
            #             "title":i["name"],
            #             "app_name":i["name"]
            #         })
            #     # frappe.log_error("bench items",i["title"]+":"+i["version"]+str(bench_data["message"]))
            #     cloud_doc.save(ignore_permissions = True)   
    except Exception:
        frappe.log_error("sync Bench error",frappe.get_traceback())

def make_request(url, method='GET', params=None,headers=None):
    token, team_id = get_token()
    # frappe.log_error('Cred',[token,team_id])
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

def get_cloud_bench_details(bench):
    cloud_bench_details = {}
    get_region = make_request(url="https://frappecloud.com/api/method/press.api.bench.regions",
                              params={"name":bench},method="POST")
    get_installed_apps = make_request(url = "https://frappecloud.com/api/method/press.api.bench.apps",
                                      params={"name":bench},method="POST")
    cloud_bench_details["region"]=get_region["message"][0].get("name")
    cloud_bench_details["installed_apps"]=get_installed_apps["message"]
    return cloud_bench_details