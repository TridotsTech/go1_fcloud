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
from datetime import datetime, timedelta
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


def _resolve_site(name):
    """Resolve a site name (local doc name or cloud site name) to the Frappe Cloud site URL.

    Accepts:
      - Local Go1 FCloud Site doc name
      - Frappe Cloud site name (e.g. "mysite.frappe.cloud")
    """
    if frappe.db.exists("Go1 FCloud Site", name):
        doc = frappe.get_doc("Go1 FCloud Site", name)
        return doc.url or doc.site_name
    # Try by cloud URL
    local_name = frappe.db.get_value("Go1 FCloud Site", {"url": name}, "name")
    if local_name:
        doc = frappe.get_doc("Go1 FCloud Site", local_name)
        return doc.url or doc.site_name
    # Try by site_name field
    local_name = frappe.db.get_value("Go1 FCloud Site", {"site_name": name}, "name")
    if local_name:
        doc = frappe.get_doc("Go1 FCloud Site", local_name)
        return doc.url or doc.site_name
    # Not found locally — use the name directly as cloud site name
    return name


def _resolve_bench(name):
    """Resolve a bench name (local doc name or cloud ID) to (doc, bench_id).

    Accepts:
      - Local Go1 FCloud Bench doc name (e.g. "kjro56udmf")
      - Frappe Cloud bench ID (e.g. "bench-50438")
    """
    # Try local doc name first
    if frappe.db.exists("Go1 FCloud Bench", name):
        doc = frappe.get_doc("Go1 FCloud Bench", name)
        return doc, doc.id or doc.bench
    # Try by cloud bench ID
    local_name = frappe.db.get_value("Go1 FCloud Bench", {"id": name}, "name")
    if local_name:
        doc = frappe.get_doc("Go1 FCloud Bench", local_name)
        return doc, doc.id or doc.bench
    # Try by bench title
    local_name = frappe.db.get_value("Go1 FCloud Bench", {"bench": name}, "name")
    if local_name:
        doc = frappe.get_doc("Go1 FCloud Bench", local_name)
        return doc, doc.id or doc.bench
    # Not found locally — use the name directly as cloud bench ID
    return None, name


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
    List all sites fetched live from Frappe Cloud with status counts.

    Args:
      status_filter: "Active" | "Inactive" | "Suspended" | "Broken" | "Attention" | None (all)
                     "Attention" matches both Broken and Suspended sites.
      search:        substring search on site name
    """
    try:
        _require_role()
        cloud_sites = unwrap(cloud_post("press.api.site.all")) or []

        # Build local doc lookup for linking local doc name
        local_sites = frappe.get_all(
            "Go1 FCloud Site",
            filters={"is_dropped": 0},
            fields=["name", "url", "bench_name", "project"],
        )
        local_by_url = {s["url"]: s for s in local_sites}

        # Count statuses across all sites (before filtering)
        attention_statuses = {"Broken", "Suspended"}
        status_counts = {}
        for s in cloud_sites:
            st = s.get("status", "")
            status_counts[st] = status_counts.get(st, 0) + 1

        total = len(cloud_sites)
        active_count = status_counts.get("Active", 0)
        attention_count = sum(status_counts.get(s, 0) for s in attention_statuses)

        sites = []
        for s in cloud_sites:
            site_name = s.get("name", "")
            status = s.get("status", "")

            # Filter by status
            if status_filter:
                if status_filter == "Attention":
                    if status not in attention_statuses:
                        continue
                elif status != status_filter:
                    continue

            if search:
                q = search.lower()
                if q not in site_name.lower() and q not in s.get("title", "").lower():
                    continue

            plan = s.get("plan") or {}
            local = local_by_url.get(site_name, {})

            sites.append({
                "name": local.get("name", "") or site_name,
                "site_name": site_name,
                "title": s.get("title", ""),
                "status": status,
                "version": s.get("version", ""),
                "region": s.get("cluster", ""),
                "plan": plan.get("name", "") if isinstance(plan, dict) else plan,
                "bench": s.get("group", ""),
                "bench_name": local.get("bench_name", ""),
                "project": local.get("project", ""),
                "creation": s.get("creation", ""),
                "app_count": s.get("app_count", 0),
            })

        return _ok({
            "site_count": {
                "total": total,
                "active": active_count,
                "attention": attention_count,
            },
            "status_list": [
                {"status": "All", "count": total},
                {"status": "Active", "count": active_count},
                {"status": "Attention", "count": attention_count},
                {"status": "Inactive", "count": status_counts.get("Inactive", 0)},
                {"status": "Suspended", "count": status_counts.get("Suspended", 0)},
                {"status": "Broken", "count": status_counts.get("Broken", 0)},
            ],
            "sites": sites,
        })
    except Exception:
        frappe.log_error("mobile_api.get_sites", frappe.get_traceback())
        return _err("Failed to fetch sites.")


@frappe.whitelist()
def get_site(name):
    """
    Return full details for a single site fetched live from Frappe Cloud.

    Args:
      name: Go1 FCloud Site doc name or Frappe Cloud site name
    """
    try:
        _require_role()
        cloud_name = _resolve_site(name)

        # Try to load local doc for extra fields
        doc = None
        if frappe.db.exists("Go1 FCloud Site", name):
            doc = frappe.get_doc("Go1 FCloud Site", name)
        else:
            local_name = frappe.db.get_value(
                "Go1 FCloud Site", {"url": cloud_name}, "name"
            ) or frappe.db.get_value(
                "Go1 FCloud Site", {"site_name": cloud_name}, "name"
            )
            if local_name:
                doc = frappe.get_doc("Go1 FCloud Site", local_name)

        # Fetch live site data from Frappe Cloud
        site_data = unwrap(
            cloud_post("press.api.site.get", {"name": cloud_name})
        ) or {}

        # Fetch installed apps live
        site_apps = (
            unwrap(
                cloud_post("press.api.site.installed_apps", {"name": cloud_name})
            )
            or []
        )
        apps = [
            {
                "app": a.get("app", ""),
                "title": a.get("title", ""),
                "repository": a.get("repository", ""),
                "branch": a.get("branch", ""),
                "current_tag": a.get("current_tag", ""),
                "next_tag": a.get("next_tag", ""),
                "update_available": bool(a.get("update_available")),
            }
            for a in site_apps
        ]

        # Fetch plan + usage from the dedicated current_plan endpoint
        # Response: { current_plan: {plan doc}, total_cpu_usage_hours, total_database_usage, ... }
        plan_info = unwrap(
            cloud_post("press.api.site.current_plan", {"name": cloud_name})
        ) or {}
        current_plan = plan_info.get("current_plan") or {}

        plan = {
            "name": current_plan.get("name", ""),
            "plan_title": current_plan.get("plan_title", ""),
            "price_inr": current_plan.get("price_inr", 0),
            "price_usd": current_plan.get("price_usd", 0),
        }

        # Limits from plan_info top level (or fall back to current_plan doc)
        cpu_limit = current_plan.get("cpu_time_per_day", 0)
        db_limit_mb = plan_info.get("max_database_usage") or current_plan.get("max_database_usage", 0)
        disk_limit_mb = plan_info.get("max_storage_usage") or current_plan.get("max_storage_usage", 0)

        # Current usage from plan_info top level
        cpu_used = round(plan_info.get("total_cpu_usage_hours", 0), 4)
        db_used_mb = round(plan_info.get("total_database_usage", 0), 2)
        disk_used_mb = round(plan_info.get("total_storage_usage", 0), 2)

        # Format storage: show in GB if limit >= 1024 MB, else MB
        def _fmt_storage(used_mb, limit_mb):
            if limit_mb >= 1024:
                used = round(used_mb / 1024, 1)
                limit = round(limit_mb / 1024, 1)
                return used, limit, f"{used} of {limit} GB"
            else:
                used = round(used_mb, 1)
                limit = round(limit_mb, 1)
                return used, limit, f"{used} of {limit} MB"

        disk_used, disk_limit, disk_display = _fmt_storage(disk_used_mb, disk_limit_mb)
        db_used, db_limit, db_display = _fmt_storage(db_used_mb, db_limit_mb)

        usage = {
            "cpu": cpu_used,
            "cpu_limit": cpu_limit,
            "cpu_display": f"{cpu_used} of {cpu_limit} hrs today",
            "database": db_used,
            "database_limit": db_limit,
            "database_display": db_display,
            "disk": disk_used,
            "disk_limit": disk_limit,
            "disk_display": disk_display,
        }

        default_domain = site_data.get("host_name", cloud_name)
        raw_domains = site_data.get("domains", [])
        domains = [
            {
                "domain": d.get("domain", ""),
                "status": d.get("status", ""),
                "primary": bool(d.get("primary") or d.get("domain") == default_domain),
                "dns_type": d.get("dns_type", ""),
                "redirect_to_primary": bool(d.get("redirect_to_primary")),
            }
            for d in raw_domains
            if isinstance(d, dict)
        ]
        if not domains:
            domains = [
                {
                    "domain": default_domain,
                    "status": "Active",
                    "primary": True,
                    "dns_type": "",
                    "redirect_to_primary": False,
                }
            ]

        return _ok(
            {
                "name": doc.name if doc else cloud_name,
                "site_name": cloud_name,
                "status": site_data.get("status", doc.status if doc else ""),
                "version": site_data.get("frappe_version", doc.version if doc else ""),
                "region": site_data.get("cluster", doc.region if doc else ""),
                "plan": plan,
                "usage": usage,
                "bench": site_data.get("group", doc.bench if doc else ""),
                "bench_name": doc.bench_name if doc else "",
                "project": doc.project if doc else "",
                "apps": apps,
                "default_domain": default_domain,
                "domains": domains,
                "setup_wizard_complete": site_data.get("setup_wizard_complete", False),
                "creation": site_data.get("creation", ""),
            }
        )
    except frappe.ValidationError as e:
        return _err(str(e))
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
              drop_site | login | setup_wizard_complete
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
            "drop_site": ("press.api.site.archive", {"name": doc.url, "force": True}),
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
        if action == "drop_site":
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
def get_site_plans(name):
    """
    Return available plans for a site, with the current plan marked.

    Args:
      name: Go1 FCloud Site doc name or Frappe Cloud site name
    """
    try:
        _require_role()
        cloud_name = _resolve_site(name)

        # Get the site's current plan
        plan_info = unwrap(
            cloud_post("press.api.site.current_plan", {"name": cloud_name})
        ) or {}
        current_plan = plan_info.get("current_plan") or {}
        current_plan_name = current_plan.get("name", "")

        # Get all available site plans
        all_plans = unwrap(cloud_get("press.api.site.get_site_plans")) or []

        plans = []
        for p in all_plans:
            plans.append({
                "name": p.get("name", ""),
                "plan_title": p.get("plan_title", ""),
                "price_inr": p.get("price_inr", 0),
                "price_usd": p.get("price_usd", 0),
                "cpu_time_per_day": p.get("cpu_time_per_day", 0),
                "max_storage_usage": p.get("max_storage_usage", 0),
                "max_database_usage": p.get("max_database_usage", 0),
                "is_current": p.get("name", "") == current_plan_name,
            })

        return _ok({
            "current_plan": current_plan_name,
            "plans": plans,
        })
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.get_site_plans", frappe.get_traceback())
        return _err("Failed to fetch site plans.")


@frappe.whitelist()
def change_site_plan(name, plan):
    """
    Change the plan of a site.

    Args:
      name: Go1 FCloud Site doc name or Frappe Cloud site name
      plan: Plan name to switch to (e.g. "USD 5")
    """
    try:
        _require_role()
        cloud_name = _resolve_site(name)

        if not plan:
            return _err("Plan name is required.")

        result = unwrap(
            cloud_post("press.api.site.change_plan", {"name": cloud_name, "plan": plan})
        )

        return _ok({"plan": plan, "result": result})
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.change_site_plan", frappe.get_traceback())
        return _err("Failed to change site plan.")


@frappe.whitelist()
def get_site_config(name):
    """
    Return the site configuration key-value pairs.

    Args:
      name: Go1 FCloud Site doc name or Frappe Cloud site name
    """
    try:
        _require_role()
        cloud_name = _resolve_site(name)
        result = unwrap(
            cloud_post("press.api.site.site_config", {"name": cloud_name})
        ) or []
        return _ok(result)
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.get_site_config", frappe.get_traceback())
        return _err("Failed to fetch site config.")


@frappe.whitelist()
def get_site_config_keys():
    """
    Return the list of standard site config keys available for selection.
    Fetched live from Frappe Cloud.
    """
    try:
        _require_role()
        result = unwrap(
            cloud_get("press.api.site.get_site_config_standard_keys")
        ) or []
        return _ok(result)
    except Exception:
        frappe.log_error("mobile_api.get_site_config_keys", frappe.get_traceback())
        return _err("Failed to fetch site config keys.")


@frappe.whitelist()
def add_site_config(name, key, value, config_type="String"):
    """
    Add or update a site configuration key.

    Args:
      name:        Go1 FCloud Site doc name or Frappe Cloud site name
      key:         Config key (e.g. "mail_server", "disable_website_cache")
      value:       Config value
      config_type: "String" | "Number" | "Boolean" | "JSON" | "Password"
    """
    try:
        _require_role()
        cloud_name = _resolve_site(name)

        if not key:
            return _err("Config key is required.")

        # Fetch existing config so we don't overwrite it
        existing = unwrap(
            cloud_post("press.api.site.site_config", {"name": cloud_name})
        ) or []

        # Build full config list: update if key exists, else append
        updated = False
        config_list = []
        for item in existing:
            if isinstance(item, dict) and item.get("key") == key:
                config_list.append({"key": key, "value": value, "type": config_type})
                updated = True
            elif isinstance(item, dict):
                config_list.append({
                    "key": item.get("key", ""),
                    "value": item.get("value", ""),
                    "type": item.get("type", "String"),
                })
        if not updated:
            config_list.append({"key": key, "value": value, "type": config_type})

        result = unwrap(
            cloud_post("press.api.site.update_config", {
                "name": cloud_name,
                "config": json.dumps(config_list),
            })
        )
        return _ok({"key": key, "value": value, "type": config_type, "result": result})
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.add_site_config", frappe.get_traceback())
        return _err("Failed to add site config.")


@frappe.whitelist()
def delete_site_config(name, key):
    """
    Delete a site configuration key.

    Args:
      name: Go1 FCloud Site doc name or Frappe Cloud site name
      key:  Config key to remove
    """
    try:
        _require_role()
        cloud_name = _resolve_site(name)

        if not key:
            return _err("Config key is required.")

        # Fetch existing config, remove the key, send full list back
        existing = unwrap(
            cloud_post("press.api.site.site_config", {"name": cloud_name})
        ) or []

        config_list = []
        found = False
        for item in existing:
            if isinstance(item, dict) and item.get("key") == key:
                found = True
                continue
            elif isinstance(item, dict):
                config_list.append({
                    "key": item.get("key", ""),
                    "value": item.get("value", ""),
                    "type": item.get("type", "String"),
                })

        if not found:
            return _err(f"Config key '{key}' not found.")

        result = unwrap(
            cloud_post("press.api.site.update_config", {
                "name": cloud_name,
                "config": json.dumps(config_list),
            })
        )
        return _ok({"key": key, "deleted": True, "result": result})
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.delete_site_config", frappe.get_traceback())
        return _err("Failed to delete site config.")


@frappe.whitelist()
def get_site_backups(name):
    """
    Return the list of backups for a site.

    Args:
      name: Go1 FCloud Site doc name or Frappe Cloud site name
    """
    try:
        _require_role()
        cloud_name = _resolve_site(name)
        result = unwrap(
            cloud_post("press.api.site.backups", {"name": cloud_name})
        ) or []

        backups = []
        for b in result:
            backups.append({
                "name": b.get("name", ""),
                "status": b.get("status", ""),
                "creation": b.get("creation", ""),
                "database_size": b.get("database_size", 0),
                "public_size": b.get("public_size", 0),
                "private_size": b.get("private_size", 0),
                "config_file_size": b.get("config_file_size", 0),
                "with_files": b.get("with_files", False),
                "offsite": b.get("offsite", False),
            })

        return _ok(backups)
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.get_site_backups", frappe.get_traceback())
        return _err("Failed to fetch site backups.")


@frappe.whitelist()
def get_site_backup_download_link(name, backup, file_type="database"):
    """
    Return a download URL for a specific backup file.

    Args:
      name:      Go1 FCloud Site doc name or Frappe Cloud site name
      backup:    Site Backup document name (from get_site_backups response "name" field)
      file_type: "database" | "public" | "private" | "config"
    """
    try:
        _require_role()
        cloud_name = _resolve_site(name)

        if not backup:
            return _err("Backup name is required.")
        if file_type not in ("database", "public", "private", "config"):
            return _err("Invalid file_type. Use: database, public, private, config")

        result = unwrap(
            cloud_post(
                "press.api.site.get_backup_link",
                {"name": cloud_name, "backup": backup, "file": file_type},
            )
        )
        if result:
            return _ok({
                "backup": backup,
                "file_type": file_type,
                "url": result,
            })
        return _err(f"No {file_type} file available for this backup.")
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error(
            "mobile_api.get_site_backup_download_link", frappe.get_traceback()
        )
        return _err("Failed to get backup download link.")


@frappe.whitelist()
def site_restore(name, backup=None, database_file=None, public_file=None, private_file=None):
    """
    Restore a site from an existing backup or uploaded files.

    Args:
      name:           Go1 FCloud Site doc name or Frappe Cloud site name
      backup:         Backup name to restore from (e.g. "2026-10-25 12:00:00.000000")
      database_file:  URL of database backup file (for restore from files)
      public_file:    URL of public files backup (optional, for restore from files)
      private_file:   URL of private files backup (optional, for restore from files)

    Either 'backup' OR 'database_file' must be provided.
    """
    try:
        _require_role()
        cloud_name = _resolve_site(name)

        if not backup and not database_file:
            return _err("Either backup name or database_file URL is required.")

        params = {"name": cloud_name}

        if backup:
            # Restore from an existing site backup
            params["files"] = {
                "database": backup,
            }
        else:
            # Restore from uploaded / remote files
            files = {"database": database_file}
            if public_file:
                files["public"] = public_file
            if private_file:
                files["private"] = private_file
            params["files"] = files

        result = unwrap(
            cloud_post("press.api.site.restore", params)
        )
        return _ok(result)
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.site_restore", frappe.get_traceback())
        return _err("Failed to restore site.")


@frappe.whitelist()
def get_remote_site_backups(url, email, password):
    """
    Fetch available backups from a remote Frappe site using credentials.

    Used in the "Restore from an existing site" flow where the user
    provides a site URL, email, and password to retrieve backup files.

    Args:
      url:      Remote Frappe site URL (e.g. "https://mysite.frappe.cloud")
      email:    Login email for the remote site
      password: Login password for the remote site
    """
    try:
        _require_role()

        if not url:
            return _err("Site URL is required.")
        if not email:
            return _err("Email is required.")
        if not password:
            return _err("Password is required.")

        result = unwrap(
            cloud_post("press.api.site.get_backup_links", {
                "url": url,
                "email": email,
                "password": password,
            })
        )
        return _ok(result)
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.get_remote_site_backups", frappe.get_traceback())
        return _err("Failed to fetch backups from remote site.")


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

        # Fetch domain and cluster info from options_for_new
        site_opts = (
            unwrap(cloud_get("press.api.site.options_for_new")) or {}
        )
        domain = site_opts.get("domain", "")
        cluster_domains = site_opts.get("cluster_specific_root_domains", [])

        # Build cluster detail map from options_for_new (has image, title)
        opts_clusters = site_opts.get("clusters", [])
        cluster_detail_map = {}
        for c in opts_clusters:
            c_name = c.get("name", "")
            if c_name:
                cluster_detail_map[c_name] = {
                    "name": c_name,
                    "title": c.get("title", ""),
                    "image": c.get("image", ""),
                    "proxy_server": c.get("proxy_server", ""),
                }

        # Enrich version clusters with image/title from options_for_new
        versions = options.get("versions", [])
        for v in versions:
            group = v.get("group") or {}
            for cl in group.get("clusters", []):
                cl_name = cl.get("name", "")
                detail = cluster_detail_map.get(cl_name)
                if detail:
                    if not cl.get("image"):
                        cl["image"] = detail["image"]
                    if not cl.get("title"):
                        cl["title"] = detail["title"]

        # Collect unique region names from versions and plans
        region_names = set()
        for v in versions:
            group = v.get("group") or {}
            for cl in group.get("clusters", []):
                cl_name = cl.get("name", "")
                if cl_name:
                    region_names.add(cl_name)
        for p in plans:
            for cl in p.get("clusters", []):
                if cl:
                    region_names.add(cl)

        # Build regions list with image and title from cluster details
        regions = []
        seen = set()
        for c in opts_clusters:
            c_name = c.get("name", "")
            if c_name and c_name not in seen:
                seen.add(c_name)
                regions.append({
                    "name": c_name,
                    "title": c.get("title", ""),
                    "image": c.get("image", ""),
                })
        # Add any region from versions/plans not already in opts_clusters
        for r_name in sorted(region_names):
            if r_name not in seen:
                seen.add(r_name)
                detail = cluster_detail_map.get(r_name, {})
                regions.append({
                    "name": r_name,
                    "title": detail.get("title", r_name),
                    "image": detail.get("image", ""),
                })

        # Extract unique providers from plans
        providers = set()
        for p in plans:
            for cp in p.get("cloud_providers", []):
                providers.add(cp)

        return _ok(
            {
                "domain": domain,
                "cluster_domains": cluster_domains,
                "regions": regions,
                "versions": versions,
                "marketplace_apps": options.get("marketplace_apps", {}),
                "plans": plans,
                "filters": {
                    "providers": sorted(providers),
                },
            }
        )
    except Exception:
        frappe.log_error("mobile_api.get_site_options", frappe.get_traceback())
        return _err("Failed to fetch site creation options.")


@frappe.whitelist()
def check_domain(subdomain, domain="frappe.cloud"):
    """
    Check whether a subdomain is available on Frappe Cloud.

    Calls press.api.site.exists to verify if the domain is already taken.

    Args:
      subdomain:  The subdomain to check (e.g. "kassss")
      domain:     The domain to check against (default "frappe.cloud")
    """
    try:
        _require_role()
        if not subdomain:
            return _err("Subdomain is required.")
        result = cloud_post(
            "press.api.site.exists", {"domain": domain, "subdomain": subdomain}
        )
        exists = unwrap(result)
        return _ok({"subdomain": subdomain, "domain": domain, "exists": exists})
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.check_domain", frappe.get_traceback())
        return _err("Failed to check domain availability.")


@frappe.whitelist()
def create_site(
    site_name, group, cluster, plan, apps=None, domain="frappe.cloud",
    share_details_consent=False, agree_region_laws=False, provider=None
):
    """
    Create a new Frappe Cloud site.

    Args:
      site_name:              subdomain (without domain suffix)
      group:                  Release Group name
      cluster:                cluster name
      plan:                   plan name
      apps:                   JSON list of app names e.g. '["erpnext"]'
      domain:                 Root domain (default "frappe.cloud", e.g. "m.frappe.cloud")
      share_details_consent:  Boolean checkbox for sharing details consent
      agree_region_laws:      Boolean checkbox for agreeing to region laws
                              (e.g. "I agree that the laws of the region selected
                              by me shall stand applicable to me and Frappe.")
      provider:               Cloud provider (e.g. "aws", "oci")
    """
    try:
        _require_role()
        requested_apps = []
        if apps:
            for a in json.loads(apps) if isinstance(apps, str) else apps:
                if a not in requested_apps:
                    requested_apps.append(a)

        # Parse booleans from string if needed
        if isinstance(share_details_consent, str):
            share_details_consent = share_details_consent.lower() in ("true", "1", "yes")
        if isinstance(agree_region_laws, str):
            agree_region_laws = agree_region_laws.lower() in ("true", "1", "yes")

        # Resolve local doc name to Frappe Cloud bench ID
        _, bench_id = _resolve_bench(group)

        # Verify bench is active
        bench = unwrap(cloud_post("press.api.bench.get", {"name": bench_id}))
        if not bench:
            return _err("Release Group not found on Frappe Cloud.")
        if bench.get("status") != "Active":
            return _err(
                f"Release Group is '{bench.get('status')}'. It must be Active to create a site."
            )

        # Fetch apps available on the bench to validate and get correct names
        bench_apps = unwrap(
            cloud_post("press.api.bench.apps", {"name": bench_id})
        ) or []
        bench_app_names = {a.get("name", ""): a for a in bench_apps}

        # Only include apps that exist on the bench (skip frappe)
        app_list = []
        for app_name in requested_apps:
            if app_name in bench_app_names:
                app_list.append(app_name)
            else:
                # Try matching by title
                matched = False
                for ba in bench_apps:
                    if ba.get("title", "").lower() == app_name.lower():
                        app_list.append(ba.get("name", ""))
                        matched = True
                        break
                if not matched:
                    return _err(
                        f"App '{app_name}' not found on this bench. "
                        f"Available: {', '.join(bench_app_names.keys())}"
                    )

        # frappe must be the first app in the list
        app_list = ["frappe"] + [a for a in app_list if a != "frappe"]

        # Resolve plan name — match by name or title from available plans
        site_plans = unwrap(cloud_get("press.api.site.get_site_plans")) or []
        resolved_plan = plan
        for p in site_plans:
            if p.get("name") == plan:
                resolved_plan = plan
                break
            if p.get("plan_title") == plan or str(p.get("name", "")) in plan:
                resolved_plan = p.get("name")
                break

        site_payload = {
            "name": site_name,
            "domain": domain,
            "apps": app_list,
            "group": bench_id,
            "cluster": cluster,
            "plan": resolved_plan,
            "share_details_consent": share_details_consent,
            "agree_region_laws": agree_region_laws,
        }
        if provider:
            site_payload["provider"] = provider

        frappe.log_error("create_site:payload", json.dumps(site_payload, default=str))
        result = cloud_post("press.api.site.new", {"site": site_payload})
        return _ok(unwrap(result))
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.create_site", frappe.get_traceback())
        return _err("Failed to create site.")


@frappe.whitelist()
def install_app(site_name, app):
    """Install an app on a site. site_name = Go1 FCloud Site doc name."""
    try:
        _require_role()
        cloud_name = _resolve_site(site_name)
        result = cloud_post(
            "press.api.site.install_app", {"name": cloud_name, "app": app}
        )
        return _ok(unwrap(result))
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.install_app", frappe.get_traceback())
        return _err("Failed to install app.")


@frappe.whitelist()
def uninstall_app(site_name, app):
    """Uninstall an app from a site. site_name = Go1 FCloud Site doc name."""
    try:
        _require_role()
        cloud_name = _resolve_site(site_name)
        result = cloud_post(
            "press.api.site.uninstall_app", {"name": cloud_name, "app": app}
        )
        return _ok(unwrap(result))
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.uninstall_app", frappe.get_traceback())
        return _err("Failed to uninstall app.")


@frappe.whitelist()
def site_login(site_name, reason=None):
    """
    Login as Administrator on a site. Returns a one-time login URL.

    Args:
      site_name:  Go1 FCloud Site doc name or Frappe Cloud site name
      reason:     Optional reason for the login
    """
    try:
        _require_role()
        cloud_name = _resolve_site(site_name)
        params = {"name": cloud_name}
        if reason:
            params["reason"] = reason
        result = unwrap(cloud_post("press.api.site.login", params))
        if result and result.get("sid"):
            site = result.get("site", cloud_name)
            login_url = f"https://{site}/api/method/login?sid={result['sid']}"
            return _ok({
                "sid": result["sid"],
                "site": site,
                "login_url": login_url,
            })
        return _ok(result)
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.site_login", frappe.get_traceback())
        return _err("Failed to generate login URL.")


@frappe.whitelist()
def setup_site(site_name):
    """
    Return a one-time login URL that opens the site's setup wizard.

    The setup wizard will mark itself complete when the user finishes it
    in the browser. We do NOT call setup_wizard_complete here because
    that restarts the site and invalidates the login session.

    Args:
      site_name: Go1 FCloud Site doc name or Frappe Cloud site name
    """
    try:
        _require_role()
        cloud_name = _resolve_site(site_name)

        result = unwrap(cloud_post("press.api.site.login", {"name": cloud_name}))

        # Handle both dict {"sid": "...", "site": "..."} and string responses
        if isinstance(result, dict) and result.get("sid"):
            sid = result["sid"]
            site_host = result.get("site", cloud_name)
        elif isinstance(result, str) and result:
            # Response may be the sid directly or a full login URL
            if result.startswith("http"):
                return _ok({
                    "login_url": result,
                    "setup_url": result,
                    "setup_wizard_url": f"https://{cloud_name}/setup-wizard",
                })
            sid = result
            site_host = cloud_name
        else:
            return _err("Failed to generate login session for the site.")

        login_url = f"https://{site_host}/api/method/login?sid={sid}"
        setup_wizard_url = f"https://{site_host}/setup-wizard"

        return _ok({
            "login_url": login_url,
            "setup_url": login_url,
            "setup_wizard_url": setup_wizard_url,
            "sid": sid,
            "site": site_host,
        })
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.setup_site", frappe.get_traceback())
        return _err("Failed to generate setup wizard URL.")


@frappe.whitelist()
def get_site_jobs(site_name):
    """
    Return running and recent jobs for a site.
    site_name = Go1 FCloud Site doc name.
    """
    try:
        _require_role()
        cloud_name = _resolve_site(site_name)
        running = (
            unwrap(cloud_post("press.api.site.running_jobs", {"name": cloud_name})) or []
        )
        activities = (
            unwrap(
                cloud_post(
                    "press.api.site.activities",
                    {
                        "filters": {"site": cloud_name},
                        "order_by": "creation desc",
                        "limit_page_length": 10,
                    },
                )
            )
            or []
        )
        return _ok({"running": running, "recent": activities})
    except frappe.ValidationError as e:
        return _err(str(e))
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


@frappe.whitelist()
def site_add_custom_domain(site_name, domain):
    """
    Add a custom domain to a site on Frappe Cloud.

    Args:
      site_name:  Go1 FCloud Site doc name or Frappe Cloud site name
      domain:     The custom domain to add (e.g. "app.example.com")
    """
    try:
        _require_role()
        if not domain:
            return _err("Domain is required.")
        cloud_name = _resolve_site(site_name)
        result = unwrap(
            cloud_post(
                "press.api.site.add_domain",
                {"name": cloud_name, "domain": domain},
            )
        )
        return _ok(result)
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.site_add_custom_domain", frappe.get_traceback())
        return _err("Failed to add custom domain.")


@frappe.whitelist()
def site_verify_dns(site_name, domain):
    """
    Verify DNS configuration for a custom domain on a site.

    Args:
      site_name:  Go1 FCloud Site doc name or Frappe Cloud site name
      domain:     The custom domain to verify DNS for (e.g. "app.example.com")
    """
    try:
        _require_role()
        if not domain:
            return _err("Domain is required.")
        cloud_name = _resolve_site(site_name)
        result = unwrap(
            cloud_post(
                "press.api.client.run_doc_method",
                {
                    "dt": "Site Domain",
                    "name": domain,
                    "method": "retry_add_domain",
                },
            )
        )
        return _ok(result)
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.site_verify_dns", frappe.get_traceback())
        return _err("Failed to verify DNS.")


# =========================================================================== #
#  BENCHES
# =========================================================================== #


@frappe.whitelist()
def get_benches(status_filter=None, search=None):
    """
    List all benches fetched live from Frappe Cloud with status counts.

    Args:
      status_filter: "Active" | "Awaiting Deploy" | "Update Available" | None (all)
      search:        substring search on bench title or id
    """
    try:
        _require_role()
        cloud_benches = (
            unwrap(
                cloud_post(
                    "press.api.bench.all",
                    {"bench_filter": {"status": "All", "tag": ""}},
                )
            )
            or []
        )

        # Build local doc lookup for linking local doc name
        local_benches = frappe.get_all(
            "Go1 FCloud Bench",
            filters={"is_dropped": 0},
            fields=["name", "bench", "id", "project"],
        )
        local_by_id = {b["id"]: b for b in local_benches if b.get("id")}
        local_by_title = {b["bench"]: b for b in local_benches if b.get("bench")}

        # Count statuses across all benches (before filtering)
        status_counts = {}
        for b in cloud_benches:
            st = b.get("status", "")
            status_counts[st] = status_counts.get(st, 0) + 1

        total = len(cloud_benches)
        active_count = status_counts.get("Active", 0)
        awaiting_deploy_count = status_counts.get("Awaiting Deploy", 0)
        update_available_count = status_counts.get("Update Available", 0)

        benches = []
        for b in cloud_benches:
            bench_id = b.get("name", "")
            title = b.get("title", "")
            status = b.get("status", "")

            if status_filter and status != status_filter:
                continue

            if search:
                q = search.lower()
                if q not in title.lower() and q not in bench_id.lower():
                    continue

            local = local_by_id.get(bench_id) or local_by_title.get(title) or {}

            benches.append({
                "name": local.get("name", ""),
                "bench_id": bench_id,
                "title": title,
                "status": status,
                "version": b.get("version", ""),
                "cluster": b.get("cluster", ""),
                "project": local.get("project", ""),
                "creation": b.get("creation", ""),
                "app_count": b.get("number_of_apps", 0),
                "site_count": b.get("number_of_sites", 0),
                "last_deploy": b.get("last_deploy", ""),
            })

        return _ok({
            "bench_count": {
                "total": total,
                "active": active_count,
                "awaiting_deploy": awaiting_deploy_count,
                "update_available": update_available_count,
            },
            "status_list": [
                {"status": "All", "count": total},
                {"status": "Active", "count": active_count},
                {"status": "Awaiting Deploy", "count": awaiting_deploy_count},
                {"status": "Update Available", "count": update_available_count},
            ],
            "benches": benches,
        })
    except Exception:
        frappe.log_error("mobile_api.get_benches", frappe.get_traceback())
        return _err("Failed to fetch benches.")


@frappe.whitelist()
def get_bench(name):
    """Return full bench details fetched live from Frappe Cloud."""
    try:
        _require_role()
        doc, bench_id = _resolve_bench(name)

        # Fetch bench info live from Frappe Cloud
        bench_data = (
            unwrap(cloud_post("press.api.bench.get", {"name": bench_id})) or {}
        )

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

        # Fetch deployed versions
        versions = (
            unwrap(cloud_post("press.api.bench.versions", {"name": bench_id}))
            or []
        )
        deploys = [
            {
                "name": v.get("name", ""),
                "status": v.get("status", ""),
                "creation": v.get("creation", ""),
            }
            for v in versions[:5]
        ]

        return _ok(
            {
                "name": doc.name if doc else "",
                "bench": bench_data.get("title", doc.bench if doc else ""),
                "bench_id": bench_id,
                "status": bench_data.get("status", ""),
                "version": bench_data.get("version", ""),
                "region": bench_data.get("cluster", ""),
                "creation": bench_data.get("creation", ""),
                "project": doc.project if doc else "",
                "update_available": update_available,
                "apps": apps,
                "recent_deploys": deploys,
            }
        )
    except Exception:
        frappe.log_error("mobile_api.get_bench", frappe.get_traceback())
        return _err(f"Failed to fetch bench: {name}")


@frappe.whitelist()
def bench_action(name, action, extra=None):
    """
    Perform an action on a bench.

    Args:
      name:   Go1 FCloud Bench doc name
      action: restart | rebuild | update_all_sites | archive |
              deploy_check | remove_app
      extra:  JSON string with optional params
              remove_app: {"app": "erpnext"}
    """
    try:
        _require_role()
        doc, bench_id = _resolve_bench(name)

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
            if doc:
                doc.is_dropped = 1
                doc.save(ignore_permissions=True)
            return _ok(unwrap(result))

        elif action == "deploy_check":
            info = unwrap(
                cloud_post("press.api.bench.deploy_information", {"name": bench_id})
            )
            return _ok(info)

        elif action == "remove_app":
            params = json.loads(extra) if extra else {}
            app = params.get("app", "")
            if not app:
                return _err("App name is required. Pass extra: {\"app\": \"erpnext\"}")
            result = cloud_post(
                "press.api.bench.remove_app", {"name": bench_id, "app": app}
            )
            return _ok(unwrap(result))

        else:
            return _err(
                f"Unknown action: {action}. Valid: restart, rebuild, update_all_sites, archive, deploy_check, remove_app"
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
        doc, bench_id = _resolve_bench(name)
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
def deploy_bench(name, apps=None, sites=None):
    """
    Deploy a bench that is in 'Awaiting Deploy' status.

    Accepts optional apps and sites selections from the caller.
    When sites are provided, uses deploy_and_update to also update
    the selected sites after deployment.

    Args:
      name:   Go1 FCloud Bench doc name
      apps:   Optional list/JSON of selected apps to deploy.
              If omitted, all apps with updates are deployed.
      sites:  Optional list/JSON of selected site names to update
              after deploy. If provided, deploy_and_update is used.
    """
    try:
        _require_role()
        doc, bench_id = _resolve_bench(name)

        # Parse JSON strings if passed from form data
        if isinstance(apps, str):
            apps = frappe.parse_json(apps)
        if isinstance(sites, str):
            sites = frappe.parse_json(sites)

        # Get deploy information (apps with pending updates)
        info = unwrap(
            cloud_post("press.api.bench.deploy_information", {"name": bench_id})
        )
        if not info:
            return _err("Could not fetch deploy information.")

        if info.get("deploy_in_progress"):
            return _err("A deploy is already in progress for this bench.")

        # Use caller-provided apps or fall back to all apps with updates
        if apps:
            apps_to_deploy = apps
        else:
            all_apps = info.get("apps", [])
            apps_to_deploy = [app for app in all_apps if app.get("update_available")]

        if not apps_to_deploy:
            return _err("No updates available to deploy.")

        # If sites provided, use deploy_and_update to deploy + update sites
        if sites:
            result = cloud_post(
                "press.api.bench.deploy_and_update",
                {"name": bench_id, "apps": apps_to_deploy, "sites": sites},
            )
        else:
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
        doc, bench_id = _resolve_bench(name)

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
    Return deploy history for a bench using versions and deploy_information.

    Args:
      name:  Go1 FCloud Bench doc name or Frappe Cloud bench ID
    """
    try:
        _require_role()
        doc, bench_id = _resolve_bench(name)

        # Fetch deployed versions (each version is a deploy)
        versions = (
            unwrap(
                cloud_post("press.api.bench.versions", {"name": bench_id})
            )
            or []
        )

        # Fetch current deploy information
        deploy_info = (
            unwrap(
                cloud_post(
                    "press.api.bench.deploy_information", {"name": bench_id}
                )
            )
            or {}
        )

        deploys = []
        for v in versions:
            deploys.append({
                "name": v.get("name", ""),
                "status": v.get("status", ""),
                "creation": v.get("creation", ""),
                "apps": v.get("apps", []),
                "sites": v.get("sites", []),
            })

        return _ok({
            "deploys": deploys,
            "deploy_in_progress": deploy_info.get("deploy_in_progress", False),
            "update_available": any(
                a.get("update_available") for a in deploy_info.get("apps", [])
            ),
        })
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


@frappe.whitelist()
def get_bench_config(name):
    """
    Return the bench configuration key-value pairs.

    Args:
      name: Go1 FCloud Bench doc name
    """
    try:
        _require_role()
        doc, bench_id = _resolve_bench(name)
        result = unwrap(
            cloud_post("press.api.bench.bench_config", {"name": bench_id})
        ) or []
        return _ok(result)
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.get_bench_config", frappe.get_traceback())
        return _err("Failed to fetch bench config.")


@frappe.whitelist()
def get_bench_config_keys():
    """
    Return the list of standard bench config keys available for selection.
    Fetched live from Frappe Cloud.
    """
    try:
        _require_role()
        result = unwrap(
            cloud_get("press.api.site.get_site_config_standard_keys")
        ) or []
        return _ok(result)
    except Exception:
        frappe.log_error("mobile_api.get_bench_config_keys", frappe.get_traceback())
        return _err("Failed to fetch bench config keys.")


@frappe.whitelist()
def add_bench_config(name, key, value, config_type="String"):
    """
    Add or update a bench configuration key.

    Args:
      name:        Go1 FCloud Bench doc name
      key:         Config key (e.g. "http_timeout", "gunicorn_workers")
      value:       Config value
      config_type: "String" | "Number" | "Boolean" | "JSON" | "Password"
    """
    try:
        _require_role()
        doc, bench_id = _resolve_bench(name)

        if not key:
            return _err("Config key is required.")

        # Fetch existing config so we don't overwrite it
        existing = unwrap(
            cloud_post("press.api.bench.bench_config", {"name": bench_id})
        ) or []

        # Build full config list: update if key exists, else append
        updated = False
        config_list = []
        for item in existing:
            if isinstance(item, dict) and item.get("key") == key:
                config_list.append({"key": key, "value": value, "type": config_type})
                updated = True
            elif isinstance(item, dict):
                config_list.append({
                    "key": item.get("key", ""),
                    "value": item.get("value", ""),
                    "type": item.get("type", "String"),
                })
        if not updated:
            config_list.append({"key": key, "value": value, "type": config_type})

        result = unwrap(
            cloud_post("press.api.bench.update_config", {
                "name": bench_id,
                "config": json.dumps(config_list),
            })
        )
        return _ok({"key": key, "value": value, "type": config_type, "result": result})
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.add_bench_config", frappe.get_traceback())
        return _err("Failed to add bench config.")


@frappe.whitelist()
def delete_bench_config(name, key):
    """
    Delete a bench configuration key.

    Args:
      name: Go1 FCloud Bench doc name
      key:  Config key to remove
    """
    try:
        _require_role()
        doc, bench_id = _resolve_bench(name)

        if not key:
            return _err("Config key is required.")

        # Fetch existing config, remove the key, send full list back
        existing = unwrap(
            cloud_post("press.api.bench.bench_config", {"name": bench_id})
        ) or []

        config_list = []
        found = False
        for item in existing:
            if isinstance(item, dict) and item.get("key") == key:
                found = True
                continue
            elif isinstance(item, dict):
                config_list.append({
                    "key": item.get("key", ""),
                    "value": item.get("value", ""),
                    "type": item.get("type", "String"),
                })

        if not found:
            return _err(f"Config key '{key}' not found.")

        result = unwrap(
            cloud_post("press.api.bench.update_config", {
                "name": bench_id,
                "config": json.dumps(config_list),
            })
        )
        return _ok({"key": key, "deleted": True, "result": result})
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.delete_bench_config", frappe.get_traceback())
        return _err("Failed to delete bench config.")


# =========================================================================== #
#  SERVERS
# =========================================================================== #


@frappe.whitelist()
def get_servers():
    """List all servers fetched live from Frappe Cloud."""
    try:
        _require_role()
        cloud_servers = unwrap(cloud_get("press.api.server.all")) or []

        # Build local doc lookup
        local_servers = frappe.get_all(
            "Go1 FCloud Server",
            fields=["name", "server_name", "server_id"],
        )
        local_by_id = {s["server_id"]: s for s in local_servers if s.get("server_id")}
        local_by_name = {s["server_name"]: s for s in local_servers if s.get("server_name")}

        servers = []
        for s in cloud_servers:
            server_id = s.get("name", "")
            title = s.get("title", "")
            plan = s.get("plan") or {}
            local = local_by_id.get(server_id) or local_by_name.get(title) or {}

            vcpu = plan.get("vcpu", 0)
            memory = plan.get("memory", 0)
            disk = plan.get("disk", 0)

            servers.append({
                "name": local.get("name", ""),
                "server_id": server_id,
                "server_name": title,
                "status": s.get("status", ""),
                "region": s.get("cluster", ""),
                "image": s.get("cluster_image", "") or s.get("image", ""),
                "vcpu": vcpu,
                "memory": memory,
                "disk": disk,
                "vcpu_display": f"{vcpu} vCPU" if vcpu else "",
                "memory_display": f"{memory} GB RAM" if memory else "",
                "disk_display": f"{disk} GB Disk" if disk else "",
                "price": plan.get("price_inr", ""),
                "creation": s.get("creation", ""),
            })

        return _ok(servers)
    except Exception:
        frappe.log_error("mobile_api.get_servers", frappe.get_traceback())
        return _err("Failed to fetch servers.")


@frappe.whitelist()
def get_server(name):
    """Return full details for a server fetched live from Frappe Cloud."""
    try:
        _require_role()
        doc = frappe.get_doc("Go1 FCloud Server", name)
        server_id = doc.server_id or doc.server_name

        # Fetch live from Frappe Cloud
        server_data = unwrap(
            cloud_post("press.api.server.get", {"name": server_id})
        ) or {}

        plan = server_data.get("plan") or {}
        return _ok(
            {
                "name": doc.name,
                "server_id": server_id,
                "server_name": server_data.get("title", doc.server_name),
                "status": server_data.get("status", doc.status),
                "region": server_data.get("cluster", doc.region),
                "vcpu": plan.get("vcpu", doc.vcpu),
                "memory": plan.get("memory", doc.memory),
                "disk": plan.get("disk", doc.disk),
                "price": plan.get("price_inr", doc.price),
                "creation": server_data.get("creation", ""),
            }
        )
    except Exception:
        frappe.log_error("mobile_api.get_server", frappe.get_traceback())
        return _err(f"Failed to fetch server: {name}")


@frappe.whitelist()
def get_server_overview(name):
    """
    Return server overview: info, plan, current resource usage.

    Args:
      name: Go1 FCloud Server doc name
    """
    try:
        _require_role()
        doc = frappe.get_doc("Go1 FCloud Server", name)
        server_id = doc.server_id or doc.server_name

        server_data = unwrap(
            cloud_post("press.api.server.get", {"name": server_id})
        ) or {}
        overview_data = unwrap(
            cloud_post("press.api.server.overview", {"name": server_id})
        ) or {}
        usage_data = unwrap(
            cloud_post("press.api.server.usage", {"name": server_id})
        ) or {}

        plan = overview_data.get("plan") or server_data.get("plan") or {}
        memory_total = plan.get("memory", doc.memory) or 0
        disk_total = plan.get("disk", doc.disk) or 0
        memory_used_mb = usage_data.get("memory", 0)
        memory_used = round(memory_used_mb / 1024, 1) if memory_used_mb else 0

        return _ok({
            "name": doc.name,
            "server_id": server_id,
            "server_name": server_data.get("title", doc.server_name),
            "status": server_data.get("status", doc.status),
            "server_type": server_data.get("server_type", ""),
            "region": server_data.get("cluster", doc.region),
            "image": server_data.get("cluster_image", "") or server_data.get("image", ""),
            "creation": server_data.get("creation", ""),
            "plan": {
                "name": plan.get("name", ""),
                "vcpu": plan.get("vcpu", doc.vcpu),
                "memory": memory_total,
                "disk": disk_total,
                "price": plan.get("price_inr", doc.price),
            },
            "usage": {
                "cpu": round(usage_data.get("vcpu", 0), 1),
                "memory": memory_used,
                "memory_total": memory_total,
                "disk": round(usage_data.get("disk", 0), 1),
                "disk_total": disk_total,
            },
            "database_server": server_data.get("database_server", ""),
            "owner": overview_data.get("owner") or {},
        })
    except Exception:
        frappe.log_error("mobile_api.get_server_overview", frappe.get_traceback())
        return _err(f"Failed to fetch server overview: {name}")


@frappe.whitelist()
def get_server_analytics(name, duration="24h", timezone=None):
    """
    Return time-series analytics for a server.

    Args:
      name:     Go1 FCloud Server doc name
      duration: "1h" | "6h" | "24h" | "7d"  (default "24h")
      timezone: IANA timezone string (default: system timezone)
    """
    try:
        _require_role()
        doc = frappe.get_doc("Go1 FCloud Server", name)
        server_id = doc.server_id or doc.server_name
        tz = timezone or frappe.utils.get_system_timezone()

        duration_map = {"1h": 1, "6h": 6, "24h": 24, "7d": 168}
        hours = duration_map.get(duration, 24)
        end = datetime.utcnow()
        start = end - timedelta(hours=hours)
        start_str = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end_str = end.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        base_params = {
            "name": server_id,
            "timezone": tz,
            "start": start_str,
            "end": end_str,
        }

        metrics = {}
        for metric in ("cpu", "memory", "network", "iops"):
            params = {**base_params, "query": metric}
            result = unwrap(cloud_post("press.api.server.analytics", params)) or {}
            datasets = result.get("datasets") or []
            labels = result.get("labels") or []
            values = datasets[0]["data"] if datasets else []
            avg_val = round(sum(values) / len(values), 2) if values else 0
            peak_val = round(max(values), 2) if values else 0
            metrics[metric] = {
                "datasets": datasets,
                "labels": labels,
                "avg": avg_val,
                "peak": peak_val,
            }

        return _ok(metrics)
    except Exception:
        frappe.log_error("mobile_api.get_server_analytics", frappe.get_traceback())
        return _err(f"Failed to fetch server analytics: {name}")


@frappe.whitelist()
def server_action(name, action, extra=None):
    """
    Perform an action on a server.

    Args:
      name:   Go1 FCloud Server doc name
      action: reboot | archive | rename | change_plan
      extra:  JSON string with optional params
              rename: {"title": "new-name"}
              change_plan: {"plan": "plan-name"}
    """
    try:
        _require_role()
        doc = frappe.get_doc("Go1 FCloud Server", name)
        server_id = doc.server_id or doc.server_name
        if not server_id:
            return _err("Server ID not set.")

        params = json.loads(extra) if extra else {}

        action_map = {
            "reboot": ("press.api.server.reboot", {"name": server_id}),
            "archive": ("press.api.server.archive", {"name": server_id}),
            "rename": (
                "press.api.server.rename",
                {"name": server_id, "title": params.get("title", "")},
            ),
            "change_plan": (
                "press.api.server.change_plan",
                {"name": server_id, "plan": params.get("plan", "")},
            ),
        }

        if action not in action_map:
            return _err(f"Unknown action: {action}. Valid: {', '.join(action_map)}")

        endpoint, payload = action_map[action]
        result = cloud_post(endpoint, payload)

        # Post-action local state update
        if action == "archive":
            doc.status = "Deleted"
            doc.save(ignore_permissions=True)
        elif action == "rename" and params.get("title"):
            doc.server_name = params["title"]
            doc.save(ignore_permissions=True)

        return _ok({"action": action, "result": unwrap(result)})
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.server_action", frappe.get_traceback())
        return _err(f"Action '{action}' failed.")


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
                "app_plan": plan,
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
