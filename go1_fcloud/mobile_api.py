# Copyright (c) 2024, Tridots Tech and contributors
# For license information, please see license.txt
#
# mobile_api.py — REST API layer for the mobile app.
#
# Architecture:
#   Mobile App  ──►  This Frappe instance (internal)
#                       └── go1_fcloud.mobile_api.*
#                               └── Frappe Cloud APIs (proxy)
#
# Mobile app authenticates to *this* Frappe instance using standard
# Frappe token auth (api_key:api_secret of the internal user).
# This layer adds:
#   - Role-based access control (System Manager / Frappe Cloud User)
#   - Response normalization (consistent JSON structure)
#   - Local caching of synced data
#   - Abstraction of cloud API quirks from mobile clients
#
# All endpoints return:
#   { "success": true, "data": <payload> }          on success
#   { "success": false, "error": "<message>" }       on failure

import frappe
import json
from go1_fcloud.utils import cloud_get, cloud_post, unwrap

MOBILE_ROLES = ("System Manager", "Frappe Cloud User")


def _require_role():
	roles = frappe.get_roles(frappe.session.user)
	if not any(r in roles for r in MOBILE_ROLES):
		frappe.throw("Access denied.", frappe.PermissionError)


def _ok(data):
	return {"success": True, "data": data}


def _err(msg):
	return {"success": False, "error": msg}


# =========================================================================== #
#  DASHBOARD
# =========================================================================== #

@frappe.whitelist()
def dashboard():
	"""
	Return a summary of all resources for the mobile home screen.

	Response:
	  sites:    { total, active, inactive, updating }
	  benches:  { total, active }
	  servers:  { total, active }
	  account:  { team, balance }
	"""
	try:
		_require_role()
		sites = frappe.get_all(
			"Go1 FCloud Site",
			filters={"is_dropped": 0},
			fields=["status"],
		)
		benches = frappe.get_all(
			"Go1 FCloud Bench",
			filters={"is_dropped": 0},
			fields=["status"],
		)
		servers = frappe.get_all("Go1 FCloud Server", fields=["status"])

		site_stats = {
			"total": len(sites),
			"active": sum(1 for s in sites if s["status"] == "Active"),
			"inactive": sum(1 for s in sites if s["status"] == "Inactive"),
			"updating": sum(1 for s in sites if s["status"] in ("Installing", "Updating", "Migrating")),
		}
		bench_stats = {
			"total": len(benches),
			"active": sum(1 for b in benches if b["status"] == "Active"),
		}
		server_stats = {
			"total": len(servers),
			"active": sum(1 for s in servers if s["status"] == "Active"),
		}

		return _ok({
			"sites": site_stats,
			"benches": bench_stats,
			"servers": server_stats,
		})
	except Exception:
		frappe.log_error("mobile_api.dashboard", frappe.get_traceback())
		return _err("Failed to load dashboard.")


# =========================================================================== #
#  SITES
# =========================================================================== #

@frappe.whitelist()
def get_sites(status_filter=None, search=None):
	"""
	List all non-dropped sites with summary fields.

	Args:
	  status_filter: "Active" | "Inactive" | "Updating" | None (all)
	  search:        substring search on site_name or url
	"""
	try:
		_require_role()
		filters = {"is_dropped": 0}
		if status_filter:
			filters["status"] = status_filter

		sites = frappe.get_all(
			"Go1 FCloud Site",
			filters=filters,
			fields=[
				"name", "site_name", "url", "status", "bench_status",
				"version", "region", "plan", "bench_name", "project",
			],
		)

		if search:
			q = search.lower()
			sites = [s for s in sites if q in (s.get("site_name") or "").lower()
			         or q in (s.get("url") or "").lower()]

		return _ok(sites)
	except Exception:
		frappe.log_error("mobile_api.get_sites", frappe.get_traceback())
		return _err("Failed to fetch sites.")


@frappe.whitelist()
def get_site(name):
	"""
	Return full details for a single site, including jobs and installed apps.

	Args:
	  name: Go1 FCloud Site doc name
	"""
	try:
		_require_role()
		doc = frappe.get_doc("Go1 FCloud Site", name)
		apps = [
			{"app": a.title, "repo": a.app_name}
			for a in (doc.custom or [])
		]
		jobs = [
			{
				"type": j.title,
				"status": j.status,
				"created": str(j.creation),
				"completed": j.completed,
				"duration": j.duration,
			}
			for j in (doc.jobs or [])
		]
		return _ok({
			"name": doc.name,
			"site_name": doc.site_name,
			"url": doc.url,
			"status": doc.status,
			"bench_status": doc.bench_status,
			"version": doc.version,
			"region": doc.region,
			"plan": doc.plan,
			"bench_name": doc.bench_name,
			"bench": doc.bench,
			"project": doc.project,
			"apps": apps,
			"recent_jobs": jobs[:5],
			"is_dropped": doc.is_dropped,
		})
	except Exception:
		frappe.log_error("mobile_api.get_site", frappe.get_traceback())
		return _err(f"Failed to fetch site: {name}")


@frappe.whitelist()
def site_action(name, action, extra=None):
	"""
	Perform an action on a site.

	Args:
	  name:   Go1 FCloud Site doc name
	  action: activate | deactivate | backup | migrate | clear_cache |
	          archive | login | setup_wizard_complete
	  extra:  JSON string with optional params (e.g. {"with_files": true})
	"""
	try:
		_require_role()
		doc = frappe.get_doc("Go1 FCloud Site", name)
		if not doc.url:
			return _err("Site URL not set.")

		params = json.loads(extra) if extra else {}

		action_map = {
			"activate":               ("press.api.site.activate",               {"name": doc.url}),
			"deactivate":             ("press.api.site.deactivate",             {"name": doc.url}),
			"backup":                 ("press.api.site.backup",                 {"name": doc.url, "with_files": params.get("with_files", True)}),
			"migrate":                ("press.api.site.migrate",                {"name": doc.url}),
			"clear_cache":            ("press.api.site.clear_cache",            {"name": doc.url}),
			"archive":                ("press.api.site.archive",                {"name": doc.url, "force": True}),
			"login":                  ("press.api.site.login",                  {"name": doc.url}),
			"setup_wizard_complete":  ("press.api.site.setup_wizard_complete",  {"name": doc.url}),
		}

		if action not in action_map:
			return _err(f"Unknown action: {action}. Valid: {', '.join(action_map)}")

		endpoint, payload = action_map[action]
		result = cloud_post(endpoint, payload)

		# Post-action local state update
		if action == "archive":
			doc.is_dropped = 1
			doc.status = "Archived"
			doc.save(ignore_permissions=True)
		elif action in ("activate", "deactivate"):
			doc.status = "Active" if action == "activate" else "Inactive"
			doc.save(ignore_permissions=True)

		return _ok({"action": action, "result": unwrap(result)})
	except frappe.ValidationError as e:
		return _err(str(e))
	except Exception:
		frappe.log_error("mobile_api.site_action", frappe.get_traceback())
		return _err(f"Action '{action}' failed.")


@frappe.whitelist()
def get_site_options():
	"""
	Return all options needed to create a new site:
	  groups, clusters, plans, shared_options.
	"""
	try:
		_require_role()
		plans = unwrap(cloud_get("press.api.site.get_site_plans")) or []
		options = unwrap(cloud_post("press.api.site.get_new_site_options")) or {}
		bench_list = unwrap(cloud_post("press.api.bench.all")) or []
		return _ok({"plans": plans, "options": options, "benches": bench_list})
	except Exception:
		frappe.log_error("mobile_api.get_site_options", frappe.get_traceback())
		return _err("Failed to fetch site creation options.")


@frappe.whitelist()
def create_site(site_name, group, cluster, plan, apps=None):
	"""
	Create a new Frappe Cloud site.

	Args:
	  site_name: subdomain (without .frappe.cloud)
	  group:     Release Group name
	  cluster:   cluster name
	  plan:      plan name
	  apps:      JSON list of app names e.g. '["erpnext"]'
	"""
	try:
		_require_role()
		app_list = ["frappe"]
		if apps:
			for a in (json.loads(apps) if isinstance(apps, str) else apps):
				if a not in app_list:
					app_list.append(a)

		# Verify bench is active
		bench = unwrap(cloud_post("press.api.bench.get", {"name": group}))
		if not bench:
			return _err("Release Group not found on Frappe Cloud.")
		if bench.get("status") != "Active":
			return _err(f"Release Group is '{bench.get('status')}'. It must be Active to create a site.")

		result = cloud_post(
			"press.api.site.new",
			{"site": {"name": site_name, "apps": app_list, "group": group,
			          "cluster": cluster, "plan": plan}},
		)
		return _ok(unwrap(result))
	except frappe.ValidationError as e:
		return _err(str(e))
	except Exception:
		frappe.log_error("mobile_api.create_site", frappe.get_traceback())
		return _err("Failed to create site.")


@frappe.whitelist()
def install_app(site_name, app):
	"""Install an app on a site (site_name = cloud URL like 'xxx.frappe.cloud')."""
	try:
		_require_role()
		result = cloud_post("press.api.site.install_app", {"name": site_name, "app": app})
		return _ok(unwrap(result))
	except Exception:
		frappe.log_error("mobile_api.install_app", frappe.get_traceback())
		return _err("Failed to install app.")


@frappe.whitelist()
def uninstall_app(site_name, app):
	"""Uninstall an app from a site."""
	try:
		_require_role()
		result = cloud_post("press.api.site.uninstall_app", {"name": site_name, "app": app})
		return _ok(unwrap(result))
	except Exception:
		frappe.log_error("mobile_api.uninstall_app", frappe.get_traceback())
		return _err("Failed to uninstall app.")


@frappe.whitelist()
def site_login(site_name):
	"""Get a one-time admin login URL for the site."""
	try:
		_require_role()
		result = unwrap(cloud_post("press.api.site.login", {"name": site_name}))
		return _ok(result)
	except Exception:
		frappe.log_error("mobile_api.site_login", frappe.get_traceback())
		return _err("Failed to generate login URL.")


@frappe.whitelist()
def get_site_jobs(site_name):
	"""
	Return running and recent jobs for a site.
	CHANGE: uses running_jobs + activities (replaces old press.api.site.jobs).
	"""
	try:
		_require_role()
		running = unwrap(cloud_post("press.api.site.running_jobs", {"name": site_name})) or []
		activities = unwrap(
			cloud_post(
				"press.api.site.activities",
				{"filters": {"site": site_name}, "order_by": "creation desc", "limit_page_length": 10},
			)
		) or []
		return _ok({"running": running, "recent": activities})
	except Exception:
		frappe.log_error("mobile_api.get_site_jobs", frappe.get_traceback())
		return _err("Failed to fetch site jobs.")


@frappe.whitelist()
def poll_job(job_name):
	"""
	Poll the status of a specific job by name.
	Endpoint: press.api.site.get_job_status (replaces press.api.site.job)
	"""
	try:
		_require_role()
		result = unwrap(cloud_post("press.api.site.get_job_status", {"job_name": job_name}))
		return _ok(result)
	except Exception:
		frappe.log_error("mobile_api.poll_job", frappe.get_traceback())
		return _err("Failed to poll job status.")


# =========================================================================== #
#  BENCHES
# =========================================================================== #

@frappe.whitelist()
def get_benches(search=None):
	"""List all benches with summary info."""
	try:
		_require_role()
		benches = frappe.get_all(
			"Go1 FCloud Bench",
			filters={"is_dropped": 0},
			fields=["name", "bench", "status", "version", "region", "server_id", "project"],
		)
		if search:
			q = search.lower()
			benches = [b for b in benches if q in (b.get("bench") or "").lower()]
		return _ok(benches)
	except Exception:
		frappe.log_error("mobile_api.get_benches", frappe.get_traceback())
		return _err("Failed to fetch benches.")


@frappe.whitelist()
def get_bench(name):
	"""Return full bench details including apps and recent deploys."""
	try:
		_require_role()
		doc = frappe.get_doc("Go1 FCloud Bench", name)
		apps = [{"name": a.title, "source": a.name1} for a in (doc.apps or [])]
		deploys = [
			{
				"name": d.title,
				"status": d.status,
				"apps": d.apps,
				"created": str(d.created_on),
				"completed": d.completed,
				"duration": d.duration,
			}
			for d in (doc.deploy or [])[:5]
		]
		sites = [{"url": s.sites} for s in (doc.linked_sites or [])]
		return _ok({
			"name": doc.name,
			"bench": doc.bench,
			"status": doc.status,
			"version": doc.version,
			"region": doc.region,
			"server_id": doc.server_id,
			"project": doc.project,
			"apps": apps,
			"recent_deploys": deploys,
			"linked_sites": sites,
		})
	except Exception:
		frappe.log_error("mobile_api.get_bench", frappe.get_traceback())
		return _err(f"Failed to fetch bench: {name}")


@frappe.whitelist()
def bench_action(name, action):
	"""
	Perform an action on a bench.

	Args:
	  name:   Go1 FCloud Bench doc name
	  action: restart | rebuild | update_all_sites | archive | deploy_check
	"""
	try:
		_require_role()
		doc = frappe.get_doc("Go1 FCloud Bench", name)
		bench_id = doc.id or doc.bench  # Release Group internal ID

		if action == "restart":
			# Restart needs bench *version* ID, not Release Group ID
			versions = unwrap(cloud_post("press.api.bench.versions", {"name": bench_id})) or []
			if not versions:
				return _err("No deployed version found. Deploy the bench first.")
			result = cloud_post("press.api.bench.restart", {"name": versions[0]["name"]})
			return _ok(unwrap(result))

		elif action == "rebuild":
			versions = unwrap(cloud_post("press.api.bench.versions", {"name": bench_id})) or []
			if not versions:
				return _err("No deployed version found. Deploy the bench first.")
			result = cloud_post("press.api.bench.rebuild", {"name": versions[0]["name"]})
			return _ok(unwrap(result))

		elif action == "update_all_sites":
			result = cloud_post("press.api.bench.update_all_sites", {"name": bench_id})
			return _ok(unwrap(result))

		elif action == "archive":
			result = cloud_post("press.api.bench.archive", {"name": bench_id})
			doc.is_dropped = 1
			doc.save(ignore_permissions=True)
			return _ok(unwrap(result))

		elif action == "deploy_check":
			info = unwrap(cloud_post("press.api.bench.deploy_information", {"name": bench_id}))
			return _ok(info)

		else:
			return _err(f"Unknown action: {action}. Valid: restart, rebuild, update_all_sites, archive, deploy_check")

	except frappe.ValidationError as e:
		return _err(str(e))
	except Exception:
		frappe.log_error("mobile_api.bench_action", frappe.get_traceback())
		return _err(f"Action '{action}' failed.")


@frappe.whitelist()
def get_bench_jobs(bench_id):
	"""
	Return running jobs for a bench (Release Group).
	Uses press.api.bench.running_jobs.
	"""
	try:
		_require_role()
		running = unwrap(cloud_post("press.api.bench.running_jobs", {"name": bench_id})) or []
		return _ok(running)
	except Exception:
		frappe.log_error("mobile_api.get_bench_jobs", frappe.get_traceback())
		return _err("Failed to fetch bench jobs.")


# =========================================================================== #
#  SERVERS
# =========================================================================== #

@frappe.whitelist()
def get_servers():
	"""List all servers."""
	try:
		_require_role()
		servers = frappe.get_all(
			"Go1 FCloud Server",
			fields=["name", "server_name", "server_id", "status", "region",
			        "vcpu", "memory", "disk", "price"],
		)
		return _ok(servers)
	except Exception:
		frappe.log_error("mobile_api.get_servers", frappe.get_traceback())
		return _err("Failed to fetch servers.")


@frappe.whitelist()
def get_server(name):
	"""Return details for a specific server."""
	try:
		_require_role()
		doc = frappe.get_doc("Go1 FCloud Server", name)
		return _ok({
			"name": doc.name,
			"server_name": doc.server_name,
			"server_id": doc.server_id,
			"status": doc.status,
			"region": doc.region,
			"vcpu": doc.vcpu,
			"memory": doc.memory,
			"disk": doc.disk,
			"price": doc.price,
		})
	except Exception:
		frappe.log_error("mobile_api.get_server", frappe.get_traceback())
		return _err(f"Failed to fetch server: {name}")


# =========================================================================== #
#  ACCOUNT
# =========================================================================== #

@frappe.whitelist()
def get_account():
	"""Return Frappe Cloud account info and billing details."""
	try:
		_require_role()
		account = unwrap(cloud_post("press.api.account.get"))
		billing = unwrap(cloud_post("press.api.account.get_billing_information"))
		return _ok({"account": account, "billing": billing})
	except Exception:
		frappe.log_error("mobile_api.get_account", frappe.get_traceback())
		return _err("Failed to fetch account info.")


# =========================================================================== #
#  NOTIFICATIONS
# =========================================================================== #

@frappe.whitelist()
def get_notifications(limit=20, offset=0):
	"""
	Return Frappe Cloud notifications for the team.
	Endpoint: press.api.notifications.get_notifications
	"""
	try:
		_require_role()
		result = unwrap(
			cloud_post(
				"press.api.notifications.get_notifications",
				{"limit_start": int(offset), "limit_page_length": int(limit)},
			)
		)
		return _ok(result)
	except Exception:
		frappe.log_error("mobile_api.get_notifications", frappe.get_traceback())
		return _err("Failed to fetch notifications.")


@frappe.whitelist()
def mark_notifications_read():
	"""Mark all Frappe Cloud notifications as read."""
	try:
		_require_role()
		cloud_post("press.api.notifications.mark_all_notifications_as_read")
		return _ok({"message": "All notifications marked as read."})
	except Exception:
		frappe.log_error("mobile_api.mark_notifications_read", frappe.get_traceback())
		return _err("Failed to mark notifications as read.")


@frappe.whitelist()
def get_unread_notification_count():
	"""Return unread notification count."""
	try:
		_require_role()
		result = unwrap(cloud_post("press.api.notifications.get_unread_count"))
		return _ok({"count": result})
	except Exception:
		frappe.log_error("mobile_api.get_unread_notification_count", frappe.get_traceback())
		return _err("Failed to fetch notification count.")


# =========================================================================== #
#  MARKETPLACE
# =========================================================================== #

@frappe.whitelist()
def get_marketplace_apps(search=None):
	"""List Frappe Cloud marketplace apps."""
	try:
		_require_role()
		apps = unwrap(cloud_post("press.api.marketplace.get_apps")) or []
		if search:
			q = search.lower()
			apps = [a for a in apps if q in (a.get("title") or a.get("name") or "").lower()]
		return _ok(apps)
	except Exception:
		frappe.log_error("mobile_api.get_marketplace_apps", frappe.get_traceback())
		return _err("Failed to fetch marketplace apps.")


# =========================================================================== #
#  SYNC  (pull Frappe Cloud data into local Frappe DocTypes)
# =========================================================================== #

@frappe.whitelist()
def sync_all():
	"""
	Enqueue sync of sites, benches, and servers from Frappe Cloud.
	Returns immediately; sync runs in the background.
	"""
	try:
		_require_role()
		from go1_fcloud.go1_fcloud.doctype.go1_fcloud_site.go1_fcloud_site import sync_site
		from go1_fcloud.go1_fcloud.doctype.go1_fcloud_bench.go1_fcloud_bench import sync_bench
		from go1_fcloud.go1_fcloud.doctype.go1_fcloud_server.go1_fcloud_server import sync_server

		frappe.enqueue(sync_bench, queue="long", job_name="fc_sync_bench")
		frappe.enqueue(sync_server, queue="long", job_name="fc_sync_server")
		frappe.enqueue(sync_site, queue="long", job_name="fc_sync_site")

		return _ok({"message": "Sync started in background. Refresh after a minute."})
	except Exception:
		frappe.log_error("mobile_api.sync_all", frappe.get_traceback())
		return _err("Failed to start sync.")


@frappe.whitelist()
def sync_sites_only():
	"""Enqueue site sync only."""
	try:
		_require_role()
		from go1_fcloud.go1_fcloud.doctype.go1_fcloud_site.go1_fcloud_site import sync_site
		frappe.enqueue(sync_site, queue="long", job_name="fc_sync_site")
		return _ok({"message": "Site sync started."})
	except Exception:
		frappe.log_error("mobile_api.sync_sites_only", frappe.get_traceback())
		return _err("Failed to start site sync.")


@frappe.whitelist()
def sync_benches_only():
	"""Enqueue bench sync only."""
	try:
		_require_role()
		from go1_fcloud.go1_fcloud.doctype.go1_fcloud_bench.go1_fcloud_bench import sync_bench
		frappe.enqueue(sync_bench, queue="long", job_name="fc_sync_bench")
		return _ok({"message": "Bench sync started."})
	except Exception:
		frappe.log_error("mobile_api.sync_benches_only", frappe.get_traceback())
		return _err("Failed to start bench sync.")


# =========================================================================== #
#  DOMAIN CHECK (check subdomain availability before site creation)
# =========================================================================== #

@frappe.whitelist()
def check_subdomain(subdomain):
	"""
	Check if a subdomain is available on frappe.cloud.
	CHANGE: press.api.site.exists → press.api.site.domain_exists(domain)
	"""
	try:
		_require_role()
		domain = f"{subdomain}.frappe.cloud"
		result = cloud_post("press.api.site.domain_exists", {"domain": domain})
		exists = bool(unwrap(result))
		return _ok({"subdomain": subdomain, "available": not exists})
	except Exception:
		frappe.log_error("mobile_api.check_subdomain", frappe.get_traceback())
		return _err("Failed to check subdomain availability.")


# =========================================================================== #
#  PROJECT MAPPING (link cloud resources to Frappe Projects)
# =========================================================================== #

@frappe.whitelist()
def get_project_resources(project):
	"""
	Return all Frappe Cloud resources (sites + benches) linked to a Project.

	Args:
	  project: Frappe Project doc name
	"""
	try:
		_require_role()
		sites = frappe.get_all(
			"Go1 FCloud Site",
			filters={"project": project, "is_dropped": 0},
			fields=["name", "site_name", "url", "status", "plan"],
		)
		benches = frappe.get_all(
			"Go1 FCloud Bench",
			filters={"project": project, "is_dropped": 0},
			fields=["name", "bench", "status", "version"],
		)
		return _ok({"sites": sites, "benches": benches})
	except Exception:
		frappe.log_error("mobile_api.get_project_resources", frappe.get_traceback())
		return _err("Failed to fetch project resources.")
