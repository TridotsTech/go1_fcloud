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
        # Fetch live counts from Frappe Cloud
        cloud_sites = unwrap(cloud_post("press.api.site.all")) or []
        cloud_benches = (
            unwrap(
                cloud_post(
                    "press.api.bench.all",
                    {"bench_filter": {"status": "All", "tag": ""}},
                )
            )
            or []
        )
        cloud_servers = (cloud_get("press.api.server.all") or {}).get("message", []) or []

        site_stats = {
            "total": len(cloud_sites),
            "active": sum(1 for s in cloud_sites if s.get("status") == "Active"),
            "inactive": sum(1 for s in cloud_sites if s.get("status") == "Inactive"),
            "suspended": sum(1 for s in cloud_sites if s.get("status") == "Suspended"),
            "updating": sum(
                1
                for s in cloud_sites
                if s.get("status") in ("Installing", "Updating", "Migrating")
            ),
        }
        bench_stats = {
            "total": len(cloud_benches),
            "active": sum(1 for b in cloud_benches if b.get("status") == "Active"),
        }
        server_stats = {
            "total": len(cloud_servers),
            "active": sum(1 for s in cloud_servers if s.get("status") == "Active"),
        }

        return _ok(
            {
                "sites": site_stats,
                "benches": bench_stats,
                "servers": server_stats,
            }
        )
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
                "name",
                "site_name",
                "url",
                "status",
                "bench_status",
                "version",
                "region",
                "plan",
                "bench_name",
                "project",
            ],
        )

        if search:
            q = search.lower()
            sites = [
                s
                for s in sites
                if q in (s.get("site_name") or "").lower()
                or q in (s.get("url") or "").lower()
            ]

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
        apps = [{"app": a.title, "repo": a.app_name} for a in (doc.custom or [])]
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
        return _ok(
            {
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
            }
        )
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
            "activate": ("press.api.site.activate", {"name": doc.url}),
            "deactivate": ("press.api.site.deactivate", {"name": doc.url}),
            "backup": (
                "press.api.site.backup",
                {"name": doc.url, "with_files": params.get("with_files", True)},
            ),
            "migrate": ("press.api.site.migrate", {"name": doc.url}),
            "clear_cache": ("press.api.site.clear_cache", {"name": doc.url}),
            "archive": ("press.api.site.archive", {"name": doc.url, "force": True}),
            "login": ("press.api.site.login", {"name": doc.url}),
            "setup_wizard_complete": (
                "press.api.site.setup_wizard_complete",
                {"name": doc.url},
            ),
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
def get_site_options(bench_name=None):
    """
    Return options needed to create a new site.

    With bench_name:
      Returns apps, clusters and plans for that private bench.

    Without bench_name:
      Returns Framework Versions (each with selectable apps and
      regions/clusters), Plans (with cloud_provider and cluster info),
      and marketplace app details (image, description).

    Args:
      bench_name:  Optional Go1 FCloud Bench doc name for private bench sites.
    """
    try:
        _require_role()

        if bench_name:
            doc = frappe.get_doc("Go1 FCloud Bench", bench_name)
            bench_id = doc.id or doc.bench
            options = (
                unwrap(
                    cloud_post(
                        "press.api.site.get_new_site_options",
                        {"group": bench_id},
                    )
                )
                or {}
            )
        else:
            options = (
                unwrap(cloud_post("press.api.site.get_new_site_options")) or {}
            )

        plans = unwrap(cloud_get("press.api.site.get_site_plans")) or []

        # Extract unique providers and regions from plans for filters
        providers = set()
        regions = set()
        for p in plans:
            for cp in p.get("cloud_providers", []):
                providers.add(cp)
            for cl in p.get("clusters", []):
                regions.add(cl)
        # Also collect regions from version clusters
        for v in options.get("versions", []):
            group = v.get("group") or {}
            for cl in group.get("clusters", []):
                regions.add(cl.get("name", ""))

        return _ok(
            {
                "versions": options.get("versions", []),
                "marketplace_apps": options.get("marketplace_apps", {}),
                "plans": plans,
                "filters": {
                    "providers": sorted(providers),
                    "regions": sorted(r for r in regions if r),
                },
            }
        )
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
            for a in json.loads(apps) if isinstance(apps, str) else apps:
                if a not in app_list:
                    app_list.append(a)

        # Verify bench is active
        bench = unwrap(cloud_post("press.api.bench.get", {"name": group}))
        if not bench:
            return _err("Release Group not found on Frappe Cloud.")
        if bench.get("status") != "Active":
            return _err(
                f"Release Group is '{bench.get('status')}'. It must be Active to create a site."
            )

        result = cloud_post(
            "press.api.site.new",
            {
                "site": {
                    "name": site_name,
                    "apps": app_list,
                    "group": group,
                    "cluster": cluster,
                    "plan": plan,
                }
            },
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
        result = cloud_post(
            "press.api.site.install_app", {"name": site_name, "app": app}
        )
        return _ok(unwrap(result))
    except Exception:
        frappe.log_error("mobile_api.install_app", frappe.get_traceback())
        return _err("Failed to install app.")


@frappe.whitelist()
def uninstall_app(site_name, app):
    """Uninstall an app from a site."""
    try:
        _require_role()
        result = cloud_post(
            "press.api.site.uninstall_app", {"name": site_name, "app": app}
        )
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
        running = (
            unwrap(cloud_post("press.api.site.running_jobs", {"name": site_name})) or []
        )
        activities = (
            unwrap(
                cloud_post(
                    "press.api.site.activities",
                    {
                        "filters": {"site": site_name},
                        "order_by": "creation desc",
                        "limit_page_length": 10,
                    },
                )
            )
            or []
        )
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
        result = unwrap(
            cloud_post("press.api.site.get_job_status", {"job_name": job_name})
        )
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
            fields=[
                "name",
                "bench",
                "status",
                "version",
                "region",
                "server_id",
                "project",
            ],
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
        bench_id = doc.id or doc.bench
        # Fetch apps live from Frappe Cloud
        cloud_apps = (
            unwrap(cloud_post("press.api.bench.apps", {"name": bench_id})) or []
        )
        apps = [
            {
                "name": a.get("name", ""),
                "title": a.get("title", ""),
                "branch": a.get("branch", ""),
            }
            for a in cloud_apps
        ]

        # Check if updates are available
        deploy_info = (
            unwrap(
                cloud_post(
                    "press.api.bench.deploy_information", {"name": bench_id}
                )
            )
            or {}
        )
        update_available = deploy_info.get("update_available", False)

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
        return _ok(
            {
                "name": doc.name,
                "bench": doc.bench,
                "bench_id": doc.id,
                "status": doc.status,
                "version": doc.version,
                "region": doc.region,
                "server_id": doc.server_id,
                "project": doc.project,
                "update_available": update_available,
                "apps": apps,
                "recent_deploys": deploys,
                "linked_sites": sites,
            }
        )
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
            versions = (
                unwrap(cloud_post("press.api.bench.versions", {"name": bench_id})) or []
            )
            if not versions:
                return _err("No deployed version found. Deploy the bench first.")
            result = cloud_post(
                "press.api.bench.restart", {"name": versions[0]["name"]}
            )
            return _ok(unwrap(result))

        elif action == "rebuild":
            versions = (
                unwrap(cloud_post("press.api.bench.versions", {"name": bench_id})) or []
            )
            if not versions:
                return _err("No deployed version found. Deploy the bench first.")
            result = cloud_post(
                "press.api.bench.rebuild", {"name": versions[0]["name"]}
            )
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
            info = unwrap(
                cloud_post("press.api.bench.deploy_information", {"name": bench_id})
            )
            return _ok(info)

        else:
            return _err(
                f"Unknown action: {action}. Valid: restart, rebuild, update_all_sites, archive, deploy_check"
            )

    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.bench_action", frappe.get_traceback())
        return _err(f"Action '{action}' failed.")


@frappe.whitelist()
def deploy_and_update(bench_id, apps, sites):
    """
    Deploy a new version of the bench and update all sites.
    """
    try:
        _require_role()
        deploy_result = cloud_post("press.api.bench.deploy", {"name": bench_id})
        if not unwrap(deploy_result):
            return _err("Bench deploy failed.")
        apps = json.loads(apps) if isinstance(apps, str) else apps
        sites = json.loads(sites) if isinstance(sites, str) else sites
        update_result = cloud_post(
            "press.api.bench.deploy_and_update",
            {"name": bench_id, "apps": apps, "sites": sites},
        )
        return _ok({"deploy": unwrap(deploy_result), "update": unwrap(update_result)})
    except Exception:
        frappe.log_error("mobile_api.deploy_and_update", frappe.get_traceback())
        return _err("Failed to deploy and update bench.")


@frappe.whitelist()
def get_bench_jobs(name):
    """
    Return running jobs for a bench.

    Args:
      name:  Go1 FCloud Bench doc name
    """
    try:
        _require_role()
        doc = frappe.get_doc("Go1 FCloud Bench", name)
        bench_id = doc.id or doc.bench
        running = (
            unwrap(cloud_post("press.api.bench.running_jobs", {"name": bench_id}))
            or []
        )
        return _ok(running)
    except Exception:
        frappe.log_error("mobile_api.get_bench_jobs", frappe.get_traceback())
        return _err("Failed to fetch bench jobs.")


@frappe.whitelist()
def get_bench_options():
    """
    Return options for creating a new bench:
      versions, clusters, regions, etc.
    Endpoint: press.api.bench.options
    """
    try:
        _require_role()
        result = cloud_post("press.api.bench.options")
        return _ok(unwrap(result))
    except Exception:
        frappe.log_error("mobile_api.get_bench_options", frappe.get_traceback())
        return _err("Failed to fetch bench creation options.")


@frappe.whitelist()
def create_bench(title, version, cluster, apps=None, server=None):
    """
    Create a new bench (Release Group) on Frappe Cloud.

    Args:
      title:     Bench name
      version:   Frappe version (e.g. "Version 15")
      cluster:   Cluster/region name
      apps:      JSON list of apps with title and source e.g. '[{"title": "erpnext", "source": "frappe/erpnext"}]'
      server:    Optional server ID (for self-hosted benches)
    """
    try:
        _require_role()
        app_list = []
        if apps:
            for a in json.loads(apps) if isinstance(apps, str) else apps:
                if isinstance(a, dict) and "title" in a and "source" in a:
                    src = a["source"]
                    if isinstance(src, dict):
                        src = src.get("name") or src.get("source", "")
                    app_list.append({"name": a["title"], "source": str(src)})
        if not app_list:
            options = unwrap(cloud_post("press.api.bench.options")) or {}
            frappe.log_error(
                "create_bench:options_versions",
                json.dumps(options.get("versions", []), default=str)[:3000],
            )
            frappe_source = None
            for v in options.get("versions", []):
                if v.get("name") == version:
                    for app in v.get("apps", []):
                        if app.get("name") == "frappe":
                            src = app.get("source")
                            if isinstance(src, dict):
                                src = src.get("name") or src.get("source", "")
                            frappe_source = str(src) if src else None
                            break
                    break
            if not frappe_source:
                return _err(f"Could not find frappe app source for {version}")
            app_list.append({"name": "frappe", "source": frappe_source})

        payload = {
            "bench": {
                "title": title,
                "version": version,
                "cluster": cluster if not server else None,
                "server": server or None,
                "saas_app": None,
                "apps": app_list,
            }
        }
        frappe.log_error(
            "create_bench:payload",
            json.dumps(payload, default=str),
        )
        result = cloud_post("press.api.bench.new", payload)
        bench_id = unwrap(result)
        if bench_id:
            bench_details = unwrap(
                cloud_post("press.api.bench.get", {"name": bench_id})
            )
            return _ok(bench_details)
        return _ok(unwrap(result))
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.create_bench", frappe.get_traceback())
        return _err("Failed to create bench.")


@frappe.whitelist()
def deploy_bench(name):
    """
    Deploy a bench that is in 'Awaiting Deploy' status.

    Fetches deploy information to get the list of apps with pending
    updates and triggers a deploy on Frappe Cloud.

    Args:
      name:  Go1 FCloud Bench doc name
    """
    try:
        _require_role()
        doc = frappe.get_doc("Go1 FCloud Bench", name)
        bench_id = doc.id or doc.bench

        # Get deploy information (apps with pending updates)
        info = unwrap(
            cloud_post("press.api.bench.deploy_information", {"name": bench_id})
        )
        if not info:
            return _err("Could not fetch deploy information.")

        if info.get("deploy_in_progress"):
            return _err("A deploy is already in progress for this bench.")

        apps = info.get("apps", [])
        apps_to_deploy = [app for app in apps if app.get("update_available")]
        if not apps_to_deploy:
            return _err("No updates available to deploy.")

        result = cloud_post(
            "press.api.bench.deploy", {"name": bench_id, "apps": apps_to_deploy}
        )
        candidate = unwrap(result)
        if candidate:
            return _ok({"candidate": candidate})
        return _ok(unwrap(result))
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.deploy_bench", frappe.get_traceback())
        return _err("Failed to deploy bench.")


@frappe.whitelist()
def get_bench_deploy_info(name):
    """
    Return deploy information for a bench: apps with update status
    (from/to commit, update_available flag) and sites on the bench.

    Args:
      name:  Go1 FCloud Bench doc name
    """
    try:
        _require_role()
        doc = frappe.get_doc("Go1 FCloud Bench", name)
        bench_id = doc.id or doc.bench

        info = (
            unwrap(
                cloud_post(
                    "press.api.bench.deploy_information", {"name": bench_id}
                )
            )
            or {}
        )

        apps = []
        for app in info.get("apps", []):
            apps.append(
                {
                    "name": app.get("app", ""),
                    "title": app.get("title", ""),
                    "branch": app.get("branch", ""),
                    "repository": app.get("repository", ""),
                    "repository_owner": app.get("repository_owner", ""),
                    "current_hash": app.get("current_hash", ""),
                    "next_hash": app.get("next_hash", ""),
                    "current_tag": app.get("current_tag", ""),
                    "next_tag": app.get("next_tag", ""),
                    "current_release": app.get("current_release", ""),
                    "next_release": app.get("next_release", ""),
                    "update_available": app.get("update_available", False),
                    "will_branch_change": app.get("will_branch_change", False),
                }
            )

        sites = info.get("sites", [])

        return _ok(
            {
                "update_available": info.get("update_available", False),
                "deploy_in_progress": info.get("deploy_in_progress", False),
                "number_of_apps": info.get("number_of_apps", 0),
                "removed_apps": info.get("removed_apps", []),
                "apps": apps,
                "sites": sites,
            }
        )
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error(
            "mobile_api.get_bench_deploy_info", frappe.get_traceback()
        )
        return _err("Failed to fetch bench deploy information.")


@frappe.whitelist()
def get_bench_deploys(name):
    """
    Return deploy history (candidates) for a bench.

    Args:
      name:  Go1 FCloud Bench doc name
    """
    try:
        _require_role()
        doc = frappe.get_doc("Go1 FCloud Bench", name)
        bench_id = doc.id or doc.bench
        candidates = (
            unwrap(
                cloud_post(
                    "press.api.bench.candidates",
                    {"filters": {"group": bench_id}},
                )
            )
            or {}
        )
        return _ok(candidates)
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.get_bench_deploys", frappe.get_traceback())
        return _err("Failed to fetch bench deploy history.")


@frappe.whitelist()
def get_bench_deploy_candidate(candidate_name):
    """
    Return status of a specific deploy candidate: build steps,
    apps, jobs, and current status.

    Args:
      candidate_name:  Deploy Candidate name (e.g. "deploy-candidate-00123")
    """
    try:
        _require_role()
        result = unwrap(
            cloud_post(
                "press.api.bench.candidate", {"name": candidate_name}
            )
        )
        return _ok(result)
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error(
            "mobile_api.get_bench_deploy_candidate", frappe.get_traceback()
        )
        return _err("Failed to fetch deploy candidate status.")


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
            fields=[
                "name",
                "server_name",
                "server_id",
                "status",
                "region",
                "vcpu",
                "memory",
                "disk",
                "price",
            ],
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
        return _ok(
            {
                "name": doc.name,
                "server_name": doc.server_name,
                "server_id": doc.server_id,
                "status": doc.status,
                "region": doc.region,
                "vcpu": doc.vcpu,
                "memory": doc.memory,
                "disk": doc.disk,
                "price": doc.price,
            }
        )
    except Exception:
        frappe.log_error("mobile_api.get_server", frappe.get_traceback())
        return _err(f"Failed to fetch server: {name}")


@frappe.whitelist()
def get_server_options():
    """
    Return options for creating a new server:
      clusters, plans, db_plans, etc.
    Endpoint: press.api.server.options
    """
    try:
        _require_role()
        result = cloud_post("press.api.server.options")
        return _ok(unwrap(result))
    except Exception:
        frappe.log_error("mobile_api.get_server_options", frappe.get_traceback())
        return _err("Failed to fetch server creation options.")


@frappe.whitelist()
def create_server(title, cluster, plan, db_plan):
    """
    Create a new server on Frappe Cloud.

    Args:
      title:    Server name
      cluster:  Cluster/region name
      plan:     App server plan (machine type / plan name)
      db_plan:  Database server plan (machine type / plan name)
    """
    try:
        _require_role()
        payload = {
            "server": {
                "title": title,
                "cluster": cluster,
                "plan": plan,
                "db_plan": db_plan,
            }
        }
        result = cloud_post("press.api.server.new", payload)
        server_name = unwrap(result)
        if server_name:
            return _ok({"name": server_name})
        return _ok(unwrap(result))
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.create_server", frappe.get_traceback())
        return _err("Failed to create server.")


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
        frappe.log_error(
            "mobile_api.get_unread_notification_count", frappe.get_traceback()
        )
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
            apps = [
                a for a in apps if q in (a.get("title") or a.get("name") or "").lower()
            ]
        return _ok(apps)
    except Exception:
        frappe.log_error("mobile_api.get_marketplace_apps", frappe.get_traceback())
        return _err("Failed to fetch marketplace apps.")


@frappe.whitelist()
def get_marketplace_app_list(bench_name=None, search=None):
    """
    List published Marketplace Apps available on Frappe Cloud.

    When bench_name is provided, returns apps not yet installed on that
    bench, with image, repository, branch (sources) and install counts.
    Without bench_name, returns all published marketplace apps enriched
    with image, description, repository, and branches.

    Args:
      bench_name:  Optional Go1 FCloud Bench doc name to filter apps
                   not already installed on that bench.
      search:      Optional search string to filter by app title/name.
    """
    try:
        _require_role()

        if bench_name:
            doc = frappe.get_doc("Go1 FCloud Bench", bench_name)
            bench_id = doc.id or doc.bench
            apps = (
                unwrap(
                    cloud_post("press.api.bench.all_apps", {"name": bench_id})
                )
                or []
            )
        else:
            # 1. Full published apps list (name, title, route)
            apps = (
                unwrap(
                    cloud_post("press.api.marketplace.get_marketplace_apps")
                )
                or []
            )

            # 2. Repo / branch lookup from bench options
            bench_opts = unwrap(cloud_post("press.api.bench.options")) or {}
            source_map = {}  # app_name -> {repository, branches[]}
            for ver in bench_opts.get("versions", []):
                for opt_app in ver.get("apps", []):
                    app_name = opt_app.get("name", "")
                    if app_name in source_map:
                        for src in opt_app.get("sources", []):
                            branch = src.get("branch")
                            if branch and branch not in source_map[app_name]["branches"]:
                                source_map[app_name]["branches"].append(branch)
                        continue
                    sources = opt_app.get("sources") or []
                    first = sources[0] if sources else {}
                    source_map[app_name] = {
                        "repository": (
                            f"{first.get('repository_owner', '')}/{first.get('repository', '')}"
                            if first.get("repository")
                            else ""
                        ),
                        "repository_url": first.get("repository_url", ""),
                        "branches": list(
                            {s.get("branch") for s in sources if s.get("branch")}
                        ),
                    }

            # 3. Enrich each app with image, description, repo, branches
            for app in apps:
                name = app.get("name", "")
                # Fetch detail per app (image, description)
                try:
                    detail = unwrap(
                        cloud_post("press.api.marketplace.get", {"app": name})
                    ) or {}
                except Exception:
                    detail = {}
                app["image"] = detail.get("image") or ""
                app["description"] = detail.get("description") or ""

                src = source_map.get(name, {})
                app["repository"] = src.get("repository", "")
                app["repository_url"] = src.get("repository_url", "")
                app["branches"] = src.get("branches", [])

        if search:
            q = search.lower()
            apps = [
                a
                for a in apps
                if q in (a.get("title") or a.get("name") or "").lower()
            ]
        return _ok(apps)
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error(
            "mobile_api.get_marketplace_app_list", frappe.get_traceback()
        )
        return _err("Failed to fetch marketplace app list.")


@frappe.whitelist()
def add_app_to_bench(bench_name, app, source):
    """
    Add a marketplace app to a bench (Release Group) on Frappe Cloud.

    Args:
      bench_name:  Go1 FCloud Bench doc name
      app:         App name (e.g. "erpnext")
      source:      App Source ID (e.g. "SRC-erpnext-542")
    """
    try:
        _require_role()
        doc = frappe.get_doc("Go1 FCloud Bench", bench_name)
        bench_id = doc.id or doc.bench
        result = cloud_post(
            "press.api.bench.add_app",
            {"name": bench_id, "source": source, "app": app},
        )
        return _ok(unwrap(result))
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.add_app_to_bench", frappe.get_traceback())
        return _err("Failed to add app to bench.")


@frappe.whitelist()
def get_marketplace_app_install_options(marketplace_app):
    """
    Get options for installing a marketplace app (plans, groups, clusters).

    Args:
      marketplace_app:  Marketplace App name
    """
    try:
        _require_role()
        result = cloud_post(
            "press.api.marketplace.options_for_quick_install",
            {"marketplace_app": marketplace_app},
        )
        return _ok(unwrap(result))
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error(
            "mobile_api.get_marketplace_app_install_options",
            frappe.get_traceback(),
        )
        return _err("Failed to fetch marketplace app install options.")


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
        from go1_fcloud.go1_fcloud.doctype.go1_fcloud_site.go1_fcloud_site import (
            sync_site,
        )
        from go1_fcloud.go1_fcloud.doctype.go1_fcloud_bench.go1_fcloud_bench import (
            sync_bench,
        )
        from go1_fcloud.go1_fcloud.doctype.go1_fcloud_server.go1_fcloud_server import (
            sync_server,
        )

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
        from go1_fcloud.go1_fcloud.doctype.go1_fcloud_site.go1_fcloud_site import (
            sync_site,
        )

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
        from go1_fcloud.go1_fcloud.doctype.go1_fcloud_bench.go1_fcloud_bench import (
            sync_bench,
        )

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
