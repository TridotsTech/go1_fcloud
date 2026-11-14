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

MOBILE_ROLES = ("System Manager", "FCloud","FCloud Admin")

DEFAULT_PERMISSION_DOCTYPES = [
    "Go1 FCloud Site",
    "Go1 FCloud Bench",
    "Go1 FCloud Server",
    "Go1 FCloud Configuration",
]


def _require_role():
    roles = frappe.get_roles(frappe.session.user)
    if not any(r in roles for r in MOBILE_ROLES):
        frappe.throw("Access denied.", frappe.PermissionError)


def _ok(data):
    return {"success": True, "data": data}


def _err(msg):
    return {"success": False, "error": msg}


# --------------------------------------------------------------------------- #
#  Authentication
# --------------------------------------------------------------------------- #


def _get_auth_token(user):
    """Return existing API key/secret for the user, or None."""
    api_key = frappe.db.get_value("User", user, "api_key")
    if not api_key:
        return None
    api_secret = frappe.utils.password.get_decrypted_password(
        "User", user, "api_secret"
    )
    if not api_secret:
        return None
    return {"api_key": api_key, "api_secret": api_secret}


def _generate_token(user):
    """Generate a new API key + secret for the user and return them."""
    user_doc = frappe.get_doc("User", user)
    api_key = frappe.generate_hash(length=15)
    api_secret = frappe.generate_hash(length=15)
    user_doc.api_key = api_key
    user_doc.api_secret = api_secret
    user_doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"api_key": api_key, "api_secret": api_secret}


@frappe.whitelist(allow_guest=True)
def login(usr=None, pwd=None):
    """Authenticate user and return API token + profile info.

    Validates that the user has at least one of the MOBILE_ROLES
    (System Manager, FCloud, FCloud Admin).
    """
    try:
        if not usr or not pwd:
            return {"message": "Username and password are required.", "status": "Failed"}

        frappe.local.login_manager.authenticate(usr, pwd)
        frappe.local.login_manager.post_login()

        login_response = {"message": frappe.local.response.get("message", "")}

        # API token
        token = _get_auth_token(usr)
        if not token:
            token = _generate_token(user=usr)
        login_response["api_key"] = token["api_key"]
        login_response["api_secret"] = token["api_secret"]
        login_response["status"] = "Success"

        # User info
        users = frappe.db.get_all(
            "User",
            fields=["name", "full_name", "user_image"],
            filters={"name": usr},
        )

        if users and users[0].name:
            user_name = users[0].name

            # Validate MOBILE_ROLES
            roles = frappe.get_roles(user_name)
            if not any(r in roles for r in MOBILE_ROLES):
                return {
                    "message": "Access denied. User does not have FCloud access.",
                    "status": "Failed",
                }

            has_roles = frappe.db.get_all(
                "Has Role", fields=["role"], filters={"parent": user_name}
            )
            employee = frappe.db.get_all(
                "Employee",
                fields=["name", "employee_name", "designation"],
                filters={"user_id": user_name},
            )
            customer = frappe.db.get_all(
                "Customer",
                fields=["name", "customer_name"],
                filters={"custom_customer": user_name},
            )

            login_response["roles"] = has_roles
            login_response["photo"] = users[0].user_image or ""
            login_response["full_name"] = users[0].full_name
            login_response["user_id"] = user_name

            if employee and employee[0]:
                login_response["employee_id"] = employee[0].name
                login_response["employee_name"] = employee[0].employee_name
                login_response["designation"] = employee[0].designation or ""
                login_response["full_name"] = employee[0].employee_name

            if customer and customer[0]:
                login_response["customer_id"] = customer[0].name
                login_response["customer_name"] = customer[0].customer_name
                frappe.local.response["full_name"] = customer[0].name

        return login_response
    except frappe.AuthenticationError:
        return {"message": "Invalid username or password.", "status": "Failed"}
    except Exception:
        frappe.log_error("mobile_api.login", frappe.get_traceback())
        return {"message": "Login Failed", "status": "Failed"}


# --------------------------------------------------------------------------- #
#  Team / Account
# --------------------------------------------------------------------------- #


@frappe.whitelist()
def get_teams():
    """Return the list of teams the current user belongs to on Frappe Cloud.

    Response includes the current (active) team and all switchable teams.
    """
    try:
        _require_role()
        account = unwrap(cloud_get("press.api.account.get")) or {}
        teams = account.get("teams", [])
        current_team = account.get("team", {})

        return _ok({
            "current_team": {
                "name": current_team.get("name", ""),
                "team_title": current_team.get("team_title", ""),
                "user": current_team.get("user", ""),
                "enabled": current_team.get("enabled", False),
                "parent_team": current_team.get("parent_team", ""),
            } if isinstance(current_team, dict) else {"name": str(current_team)},
            "teams": [
                {
                    "name": t.get("name", "") if isinstance(t, dict) else str(t),
                    "team_title": t.get("team_title", "") if isinstance(t, dict) else "",
                    "user": t.get("user", "") if isinstance(t, dict) else "",
                }
                for t in teams
            ],
        })
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.get_teams", frappe.get_traceback())
        return _err("Failed to fetch teams.")


@frappe.whitelist()
def switch_team(team: str):
    """Switch the active Frappe Cloud team account.

    Args:
      team: Team name (ID) to switch to.

    After switching, all subsequent Frappe Cloud API calls will operate
    under the new team context.
    """
    try:
        _require_role()
        if not team:
            return _err("Team name is required.")

        result = unwrap(
            cloud_post("press.api.account.switch_team", {"team": team})
        )
        if not result:
            return _err(f"Could not switch to team '{team}'. You may not be a member.")

        team_info = result.get("team", {}) if isinstance(result, dict) else {}
        return _ok({
            "team": {
                "name": team_info.get("name", "") if isinstance(team_info, dict) else str(team_info),
                "team_title": team_info.get("team_title", "") if isinstance(team_info, dict) else "",
                "user": team_info.get("user", "") if isinstance(team_info, dict) else "",
            },
            "message": f"Switched to team '{team}'.",
        })
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.switch_team", frappe.get_traceback())
        return _err("Failed to switch team.")


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
      - Frappe Cloud Release Group ID (e.g. "bench-50438")
      - Bench title stored in the local doc's ``bench`` field
      - Deploy Candidate / pipeline name (e.g. "734h2vihje") —
        resolved to its parent Release Group via the cloud API

    Returns:
      (doc | None, cloud_release_group_id)

    Raises:
      frappe.ValidationError if the bench cannot be resolved to a cloud ID.
    """
    doc = None

    # Try local doc name first
    if frappe.db.exists("Go1 FCloud Bench", name):
        doc = frappe.get_doc("Go1 FCloud Bench", name)
    else:
        # Try by cloud bench ID stored in the id field
        local_name = frappe.db.get_value("Go1 FCloud Bench", {"id": name}, "name")
        if local_name:
            doc = frappe.get_doc("Go1 FCloud Bench", local_name)
        else:
            # Try by bench title
            local_name = frappe.db.get_value("Go1 FCloud Bench", {"bench": name}, "name")
            if local_name:
                doc = frappe.get_doc("Go1 FCloud Bench", local_name)

    if doc:
        bench_id = doc.id
        if bench_id:
            return doc, bench_id
        # id field is empty — the local doc was never synced with the cloud
        frappe.throw(
            f"Bench '{name}' has no linked Release Group ID. Please sync benches first."
        )

    # No local doc — accept the name only if it looks like a cloud ID
    if name and name.startswith("bench-"):
        return None, name

    # Try as a Deploy Candidate / pipeline name — resolve to its
    # parent Release Group so callers get the correct bench ID.
    if name:
        try:
            candidate = unwrap(
                cloud_post(
                    "press.api.client.get",
                    {"doctype": "Deploy Candidate", "name": name},
                )
            ) or {}
            group = candidate.get("group")
            if group:
                return None, group
        except Exception:
            frappe.clear_messages()

    frappe.throw(f"Bench '{name}' not found.")


def _fetch_deploy_information(bench_id):
    """Fetch deploy information for a Release Group from Press.

    Tries the direct ``press.api.bench.deploy_information`` endpoint first.
    If that fails (the ``@protected`` decorator checks team ownership),
    falls back to ``press.api.client.get`` which uses read-only document
    access checks and may succeed when the @protected gate does not.
    The fallback constructs a minimal deploy-info dict from the Release
    Group document and its ``deployed_versions`` dashboard method.

    Note: ``press.api.client.run_doc_method`` cannot call
    ``deploy_information`` because it is not ``@dashboard_whitelist()``.
    """
    try:
        return unwrap(
            cloud_post("press.api.bench.deploy_information", {"name": bench_id})
        )
    except Exception:
        # Clear error messages from the first attempt so they don't
        # accumulate in _server_messages and confuse the client.
        frappe.clear_messages()

        # Fallback: fetch the Release Group document via the client.get
        # endpoint (read-only access) and construct basic deploy info.
        rg_doc = unwrap(
            cloud_post(
                "press.api.client.get",
                {"doctype": "Release Group", "name": bench_id},
            )
        ) or {}

        apps = []
        for app in rg_doc.get("apps", []):
            apps.append({
                "app": app.get("app", ""),
                "title": app.get("title", ""),
                "source": app.get("source", ""),
                "branch": app.get("branch", ""),
                "repository": app.get("repository", ""),
                "repository_owner": app.get("repository_owner", ""),
                "current_hash": "",
                "current_tag": "",
                "current_release": "",
                "next_release": "",
                "releases": [],
                "update_available": False,
                "will_branch_change": False,
            })

        # Try to get site list via deployed_versions (dashboard-whitelisted).
        sites = []
        try:
            versions = unwrap(
                cloud_post(
                    "press.api.client.run_doc_method",
                    {
                        "dt": "Release Group",
                        "dn": bench_id,
                        "method": "deployed_versions",
                    },
                )
            ) or []
            for v in versions:
                for s in v.get("sites", []):
                    sites.append(s)
        except Exception:
            frappe.clear_messages()

        return frappe._dict({
            "update_available": False,
            "deploy_in_progress": False,
            "number_of_apps": len(apps),
            "removed_apps": [],
            "apps": apps,
            "sites": sites,
        })


# =========================================================================== #
#  DASHBOARD
# =========================================================================== #


@frappe.whitelist()
def dashboard(activity_filter=None):
    """
    Return a summary of all resources for the mobile home screen,
    including recent activity with optional status filtering.

    Args:
      activity_filter: "Success" | "Failed" | None (all)

    Response:
      sites:           { total, active, inactive, suspended, updating }
      benches:         { total, active }
      servers:         { total, active }
      recent_activity: [
        {
          "title":    action/type label,
          "status":   "Success" | "Failed" | "Running" | "Pending",
          "type":     "site",
          "site":     cloud site name,
          "creation": ISO timestamp,
          "reason":   optional detail
        }
      ]
    """
    try:
        _require_role()

        # --- Permission flags per doctype ---
        site_perms = {
            "can_read": frappe.has_permission("Go1 FCloud Site", "read"),
            "can_create": frappe.has_permission("Go1 FCloud Site", "create"),
            "can_write": frappe.has_permission("Go1 FCloud Site", "write"),
            "can_delete": frappe.has_permission("Go1 FCloud Site", "delete"),
        }
        bench_perms = {
            "can_read": frappe.has_permission("Go1 FCloud Bench", "read"),
            "can_create": frappe.has_permission("Go1 FCloud Bench", "create"),
            "can_write": frappe.has_permission("Go1 FCloud Bench", "write"),
            "can_delete": frappe.has_permission("Go1 FCloud Bench", "delete"),
        }
        server_perms = {
            "can_read": frappe.has_permission("Go1 FCloud Server", "read"),
            "can_create": frappe.has_permission("Go1 FCloud Server", "create"),
            "can_write": frappe.has_permission("Go1 FCloud Server", "write"),
            "can_delete": frappe.has_permission("Go1 FCloud Server", "delete"),
        }

        # --- Counts from local doctypes (only if user has read permission) ---
        site_stats = {"total": 0, "active": 0, "inactive": 0, "suspended": 0, "updating": 0}
        if site_perms["can_read"]:
            all_sites = frappe.get_all(
                "Go1 FCloud Site", fields=["status"], ignore_ifnull=True
            )
            site_status_counts = {}
            for s in all_sites:
                st = s.get("status") or ""
                site_status_counts[st] = site_status_counts.get(st, 0) + 1
            site_stats = {
                "total": len(all_sites),
                "active": site_status_counts.get("Active", 0),
                "inactive": site_status_counts.get("Inactive", 0),
                "suspended": site_status_counts.get("Suspended", 0),
                "updating": sum(
                    site_status_counts.get(st, 0)
                    for st in ("Installing", "Updating", "Migrating")
                ),
            }

        bench_stats = {"total": 0, "active": 0}
        if bench_perms["can_read"]:
            all_benches = frappe.get_all(
                "Go1 FCloud Bench",
                fields=["status"],
                filters={"is_dropped": 0},
                ignore_ifnull=True,
            )
            bench_stats = {
                "total": len(all_benches),
                "active": sum(1 for b in all_benches if b.get("status") == "Active"),
            }

        server_stats = {"total": 0, "active": 0}
        if server_perms["can_read"]:
            all_servers = frappe.get_all(
                "Go1 FCloud Server", fields=["status"], ignore_ifnull=True
            )
            server_stats = {
                "total": len(all_servers),
                "active": sum(1 for s in all_servers if s.get("status") == "Active"),
            }

        # --- Recent Activity (from Frappe Cloud jobs) ---
        activities = []
        if site_perms["can_read"]:
            cloud_sites = unwrap(cloud_post("press.api.site.all")) or []
            site_names = [s.get("name") for s in cloud_sites if s.get("name")]

            for site_name in site_names[:10]:
                try:
                    site_jobs = (
                        unwrap(
                            cloud_post(
                                "press.api.site.jobs",
                                {
                                    "filters": {"site": site_name},
                                    "order_by": "creation desc",
                                    "limit_page_length": 5,
                                },
                            )
                        )
                        or []
                    )
                    for j in site_jobs:
                        activities.append(
                            {
                                "title": j.get("job_type") or "Activity",
                                "status": _normalise_activity_status(
                                    (j.get("status") or "").strip()
                                ),
                                "type": "site",
                                "site": site_name,
                                "creation": j.get("creation") or "",
                                "reason": "",
                            }
                        )
                except Exception:
                    continue

        activities.sort(key=lambda x: x.get("creation", ""), reverse=True)
        activities = activities[:20]

        # Apply activity_filter
        if activity_filter in ("Success", "Failed"):
            activities = [
                a for a in activities if a.get("status") == activity_filter
            ]

        return _ok(
            {
                "permissions": {
                    "site": site_perms,
                    "bench": bench_perms,
                    "server": server_perms,
                },
                "sites": site_stats,
                "benches": bench_stats,
                "servers": server_stats,
                "recent_activity": activities,
            }
        )
    except Exception:
        frappe.log_error("mobile_api.dashboard", frappe.get_traceback())
        return _err("Failed to load dashboard.")


def _normalise_activity_status(raw):
    """Map various cloud status strings to Success / Failed / Running / Pending."""
    raw_lower = raw.lower() if raw else ""
    if raw_lower in ("success", "completed", "active", "running successfully"):
        return "Success"
    if raw_lower in ("failure", "failed", "error", "broken", "undelivered"):
        return "Failed"
    if raw_lower in ("running", "in progress", "pending installation"):
        return "Running"
    return "Pending"


# =========================================================================== #
#  SITES
# =========================================================================== #


@frappe.whitelist()
def get_sites(status_filter=None, search=None, server=None, start=0, limit=20):
    """
    List sites from local Go1 FCloud Site doctype with permission checks.

    Uses ``frappe.get_list`` which automatically enforces the Role Permission
    Manager rules defined on Go1 FCloud Site (System Manager, FCloud,
    FCloud Admin).

    Args:
      status_filter: "Active" | "Inactive" | "Suspended" | "Broken" | "Attention" | None (all)
                     "Attention" matches both Broken and Suspended sites.
      search:        substring search on site name
      server:        filter by server name
      start:         pagination offset (default 0)
      limit:         page size (default 20)
    """
    try:
        start = frappe.utils.cint(start)
        limit = frappe.utils.cint(limit) or 20

        # Permission flags for the current user
        can_read = frappe.has_permission("Go1 FCloud Site", "read")
        can_create = frappe.has_permission("Go1 FCloud Site", "create")
        can_write = frappe.has_permission("Go1 FCloud Site", "write")
        can_delete = frappe.has_permission("Go1 FCloud Site", "delete")

        if not can_read:
            return _err("Not permitted to access Go1 FCloud Site.")

        # Build filters — frappe.get_list applies permission checks automatically
        attention_statuses = ["Broken", "Suspended"]
        filters = {"is_dropped": 0}
        if status_filter:
            if status_filter == "Attention":
                filters["status"] = ("in", attention_statuses)
            else:
                filters["status"] = status_filter
        if server:
            # Resolve server to doc name (supports doc name, server_name, server_id)
            server_doc = None
            if frappe.db.exists("Go1 FCloud Server", server):
                server_doc = server
            else:
                server_doc = frappe.db.get_value(
                    "Go1 FCloud Server", {"server_name": server}, "name"
                ) or frappe.db.get_value(
                    "Go1 FCloud Server", {"server_id": server}, "name"
                )
            if server_doc:
                # Find all bench doc names on this server
                bench_docs = frappe.get_all(
                    "Go1 FCloud Bench",
                    filters={"server": server_doc, "is_dropped": 0},
                    pluck="name",
                )
                if bench_docs:
                    filters["bench_name"] = ("in", bench_docs)
                else:
                    # No benches on this server — return empty
                    filters["bench_name"] = "___NONE___"
            else:
                # Server not found — try as bench name directly (backward compat)
                filters["bench"] = server
        if search:
            filters["url"] = ("like", f"%{search}%")

        # Status counts (across all sites, before pagination/filters)
        all_sites = frappe.get_list(
            "Go1 FCloud Site",
            filters={"is_dropped": 0},
            fields=["status"],
            ignore_ifnull=True,
        )
        status_counts = {}
        for s in all_sites:
            st = s.get("status") or ""
            status_counts[st] = status_counts.get(st, 0) + 1

        total = len(all_sites)
        active_count = status_counts.get("Active", 0)
        attention_count = sum(status_counts.get(s, 0) for s in attention_statuses)

        # Filtered + paginated site list
        site_records = frappe.get_list(
            "Go1 FCloud Site",
            filters=filters,
            fields=[
                "name", "site_name", "url", "status", "version",
                "region", "plan", "group", "bench", "bench_name",
                "bench_status", "project", "creation", "modified",
            ],
            order_by="modified desc",
            start=start,
            page_length=limit,
            ignore_ifnull=True,
        )

        # Total count for the current filter set (for pagination)
        total_filtered = frappe.db.count(
            "Go1 FCloud Site", filters=filters
        )
        has_next = (start + limit) < total_filtered

        sites = []
        for s in site_records:
            sites.append({
                "name": s.get("name", ""),
                "site_name": s.get("url", "") or s.get("site_name", ""),
                "title": s.get("site_name", ""),
                "status": s.get("status", ""),
                "version": s.get("version", ""),
                "region": s.get("region", ""),
                "plan": s.get("plan", ""),
                "group": s.get("group", ""),
                "bench": s.get("bench", ""),
                "bench_name": s.get("bench_name", ""),
                "bench_status": s.get("bench_status", ""),
                "project": s.get("project", ""),
                "creation": s.get("creation", ""),
                "modified": s.get("modified", ""),
            })

        return _ok({
            "permissions": {
                "can_read": can_read,
                "can_create": can_create,
                "can_write": can_write,
                "can_delete": can_delete,
            },
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
            "total_filtered": total_filtered,
            "start": start,
            "limit": limit,
            "has_next": has_next,
        })
    except frappe.PermissionError:
        return _err("Not permitted to access Go1 FCloud Site.")
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

        # Resolve bench_name and region from local doc or cloud group ID
        group = site_data.get("group", "")
        bench_name = (doc.bench_name if doc else "") or ""
        bench_doc = None
        if not bench_name and group:
            bench_doc = (
                frappe.get_doc("Go1 FCloud Bench", {"id": group})
                if frappe.db.exists("Go1 FCloud Bench", {"id": group})
                else None
            )
            bench_name = bench_doc.name if bench_doc else ""

        # Region: try site_data first, then local bench doc, then local site doc
        region = (
            site_data.get("cluster")
            or (site_data.get("region_info") or {}).get("title")
            or (bench_doc.region if bench_doc else "")
            or (doc.region if doc else "")
            or ""
        )

        return _ok(
            {
                "name": doc.name if doc else cloud_name,
                "site_name": cloud_name,
                "status": site_data.get("status", doc.status if doc else ""),
                "version": site_data.get("frappe_version", doc.version if doc else ""),
                "region": region,
                "plan": plan,
                "usage": usage,
                "bench": group or (doc.bench if doc else ""),
                "bench_name": bench_name,
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
        cloud_name = _resolve_site(name)

        # Try to load local doc for post-action state updates
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

        params = json.loads(extra) if extra else {}

        action_map = {
            "activate": ("press.api.site.activate", {"name": cloud_name}),
            "deactivate": ("press.api.site.deactivate", {"name": cloud_name}),
            "backup": (
                "press.api.site.backup",
                {"name": cloud_name, "with_files": params.get("with_files", True)},
            ),
            "migrate": ("press.api.site.migrate", {"name": cloud_name}),
            "clear_cache": ("press.api.site.clear_cache", {"name": cloud_name}),
            "drop_site": ("press.api.site.archive", {"name": cloud_name, "force": True}),
            "login": ("press.api.site.login", {"name": cloud_name}),
            "setup_wizard_complete": (
                "press.api.site.setup_wizard_complete",
                {"name": cloud_name},
            ),
        }

        if action not in action_map:
            return _err(f"Unknown action: {action}. Valid: {', '.join(action_map)}")

        endpoint, payload = action_map[action]
        result = cloud_post(endpoint, payload)

        # Post-action local state update
        if doc:
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
            price_inr = p.get("price_inr", 0) or 0
            price_usd = p.get("price_usd", 0) or 0
            # Keep the current plan even if ₹0; skip other ₹0 plans
            is_current = p.get("name", "") == current_plan_name
            if not price_inr and not price_usd and not is_current:
                continue
            plans.append({
                "name": p.get("name", ""),
                "plan_title": p.get("plan_title", ""),
                "price_inr": price_inr,
                "price_usd": price_usd,
                "cpu_time_per_day": p.get("cpu_time_per_day", 0),
                "max_storage_usage": p.get("max_storage_usage", 0),
                "max_database_usage": p.get("max_database_usage", 0),
                "is_current": is_current,
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
            (e.g. "mysite.frappe.cloud")
    """
    try:
        _require_role()
        cloud_name = _resolve_site(name)

        result = unwrap(
            cloud_get("press.api.site.backups", {"name": cloud_name})
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
                "database_url": b.get("database_url", ""),
                "public_url": b.get("public_url", ""),
                "private_url": b.get("private_url", ""),
                "config_file_url": b.get("config_file_url", ""),
                "remote_database_file": b.get("remote_database_file", ""),
                "remote_public_file": b.get("remote_public_file", ""),
                "remote_private_file": b.get("remote_private_file", ""),
                "remote_config_file": b.get("remote_config_file", ""),
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

        # Fetch backups list (this endpoint works) and find matching backup
        backups = unwrap(
            cloud_get("press.api.site.backups", {"name": cloud_name})
        ) or []

        backup_data = None
        for b in backups:
            if b.get("name") == backup:
                backup_data = b
                break

        if not backup_data:
            return _err(f"Backup '{backup}' not found.")

        # Map file_type to the URL field in backup data
        url_field_map = {
            "database": "database_url",
            "public": "public_url",
            "private": "private_url",
            "config": "config_file_url",
        }
        url = backup_data.get(url_field_map[file_type], "")
        if not url:
            return _err(f"No {file_type} file available for this backup.")

        return _ok({
            "backup": backup,
            "file_type": file_type,
            "url": url,
        })
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error(
            "mobile_api.get_site_backup_download_link", frappe.get_traceback()
        )
        return _err("Failed to get backup download link.")


@frappe.whitelist()
def site_restore(name, backup=None, database_file=None, public_file=None, private_file=None, skip_failing_patches=False):
    """
    Restore a site from an existing backup.

    Args:
      name:           Go1 FCloud Site doc name or Frappe Cloud site name
      backup:         Site Backup document name (from get_site_backups "name" field)
      database_file:  Remote File name OR backup database URL (resolved automatically)
      public_file:    Remote File name OR backup public URL (optional)
      private_file:   Remote File name OR backup private URL (optional)
      skip_failing_patches: Skip failing patches during restore (default False)

    Either 'backup' OR 'database_file' must be provided.
    The function resolves Remote File document names automatically —
    callers can pass a backup name, a URL, or a Remote File name.
    """
    try:
        _require_role()
        cloud_name = _resolve_site(name)

        if not backup and not database_file:
            return _err("Either backup name or database_file is required.")

        # Fetch site backups once (needed for both backup-name and URL lookups)
        all_backups = unwrap(
            cloud_get("press.api.site.backups", {"name": cloud_name})
        ) or []

        files = {}

        if backup:
            # Match by backup document name
            backup_data = next((b for b in all_backups if b.get("name") == backup), None)
            if not backup_data:
                return _err(f"Backup '{backup}' not found for this site.")

            files = _extract_remote_files(backup_data)
            if not files.get("database"):
                return _err("No remote database file found for this backup.")
        else:
            # database_file could be a Remote File name OR a backup URL.
            # If it looks like a URL, resolve it to Remote File names via backup records.
            if database_file and database_file.startswith("http"):
                backup_data = _find_backup_by_url(all_backups, database_file)
                if not backup_data:
                    return _err("Could not find a backup matching the provided URL.")
                files = _extract_remote_files(backup_data)
                if not files.get("database"):
                    return _err("No remote database file found for this backup.")
            else:
                files["database"] = database_file
                if public_file:
                    files["public"] = public_file
                if private_file:
                    files["private"] = private_file

        result = unwrap(
            cloud_post("press.api.site.restore", {
                "name": cloud_name,
                "files": files,
                "skip_failing_patches": skip_failing_patches,
            })
        )
        return _ok(result)
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.site_restore", frappe.get_traceback())
        return _err("Failed to restore site.")


def _extract_remote_files(backup_data):
    """Extract Remote File document names from a backup record."""
    files = {}
    if backup_data.get("remote_database_file"):
        files["database"] = backup_data["remote_database_file"]
    if backup_data.get("remote_public_file"):
        files["public"] = backup_data["remote_public_file"]
    if backup_data.get("remote_private_file"):
        files["private"] = backup_data["remote_private_file"]
    if backup_data.get("remote_config_file"):
        files["config"] = backup_data["remote_config_file"]
    return files


def _find_backup_by_url(backups, url):
    """Find a backup record by matching any of its URL fields."""
    # Strip query params for comparison (URLs may have different session IDs)
    clean = url.split("?")[0] if url else ""
    for b in backups:
        for field in ("database_url", "public_url", "private_url", "config_file_url"):
            val = b.get(field, "")
            if val and val.split("?")[0] == clean:
                return b
    return None


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

        # Format plans with pricing fields (skip ₹0 plans)
        formatted_plans = []
        for p in plans:
            price_inr = p.get("price_inr", 0) or 0
            price_usd = p.get("price_usd", 0) or 0
            if not price_inr and not price_usd:
                continue
            formatted_plans.append({
                "name": p.get("name", ""),
                "plan_title": p.get("plan_title", ""),
                "price_inr": price_inr,
                "price_usd": price_usd,
                "cpu_time_per_day": p.get("cpu_time_per_day", 0),
                "max_storage_usage": p.get("max_storage_usage", 0),
                "max_database_usage": p.get("max_database_usage", 0),
                "support_included": p.get("support_included", 0),
                "offsite_backups": p.get("offsite_backups", 0),
                "database_access": p.get("database_access", 0),
                "monitor_access": p.get("monitor_access", 0),
                "clusters": p.get("clusters", []),
                "cloud_providers": p.get("cloud_providers", []),
            })

        # Extract unique providers from plans
        providers = set()
        for p in formatted_plans:
            for cp in p.get("cloud_providers", []):
                providers.add(cp)

        # Build combined apps dict: marketplace apps + private bench apps
        all_apps = dict(options.get("marketplace_apps", {}))
        if bench_name:
            bench_apps = (
                unwrap(cloud_post("press.api.bench.apps", {"name": bench_id}))
                or []
            )
            for a in bench_apps:
                app_name = a.get("name", "")
                if app_name and app_name not in all_apps:
                    all_apps[app_name] = {
                        "title": a.get("title", app_name),
                        "image": a.get("image", ""),
                        "description": a.get("description", ""),
                        "app": app_name,
                        "branch": a.get("branch", ""),
                        "repository": a.get("repository", ""),
                        "repository_owner": a.get("repository_owner", ""),
                        "source": a.get("source", ""),
                    }

        return _ok(
            {
                "domain": domain,
                "cluster_domains": cluster_domains,
                "regions": regions,
                "versions": versions,
                "marketplace_apps": all_apps,
                "plans": formatted_plans,
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
    site_name, group=None, cluster=None, plan=None, apps=None,
    domain="frappe.cloud", share_details_consent=False,
    agree_region_laws=False, provider=None, server=None,
):
    """
    Create a new Frappe Cloud site.

    Args:
      site_name:              subdomain (without domain suffix)
      group:                  Release Group name / bench ID / bench title
      cluster:                cluster name (optional — auto-resolved from bench)
      plan:                   plan name (optional — uses cheapest if omitted)
      apps:                   JSON list of app names e.g. '["erpnext"]'
      domain:                 Root domain (default "frappe.cloud", e.g. "m.frappe.cloud")
      share_details_consent:  Boolean checkbox for sharing details consent
      agree_region_laws:      Boolean checkbox for agreeing to region laws
      provider:               Cloud provider (e.g. "aws", "oci")
      server:                 Go1 FCloud Server doc name, server_name, or server_id
                              (resolves to the first active bench on that server)
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

        # Resolve bench ID — from group param or via server lookup
        bench_id = None
        cloud_server_name = None  # Frappe Cloud server ID (e.g. f962-mumbai.frappe.cloud)
        group_provided = bool(group)  # Track if user explicitly provided a group
        if group:
            _, bench_id = _resolve_bench(group)
        elif server:
            # Resolve server to doc name
            server_doc = None
            if frappe.db.exists("Go1 FCloud Server", server):
                server_doc = server
            else:
                server_doc = frappe.db.get_value(
                    "Go1 FCloud Server", {"server_name": server}, "name"
                ) or frappe.db.get_value(
                    "Go1 FCloud Server", {"server_id": server}, "name"
                )
            if not server_doc:
                return _err(f"Server '{server}' not found.")

            # Get cloud server ID for the payload
            cloud_server_name = frappe.db.get_value(
                "Go1 FCloud Server", server_doc, "server_id"
            )

            # Find the first active bench on this server
            bench_doc_name = frappe.db.get_value(
                "Go1 FCloud Bench",
                {"server": server_doc, "is_dropped": 0},
                "name",
                order_by="modified desc",
            )
            if not bench_doc_name:
                return _err(f"No bench found on server '{server}'.")
            _, bench_id = _resolve_bench(bench_doc_name)
        else:
            return _err("Either 'group' (bench) or 'server' is required.")

        # Resolve cloud server ID from bench doc or server param
        if not cloud_server_name and server:
            # server param provided but cloud_server_name not yet resolved
            server_doc = None
            if frappe.db.exists("Go1 FCloud Server", server):
                server_doc = server
            else:
                server_doc = frappe.db.get_value(
                    "Go1 FCloud Server", {"server_name": server}, "name"
                ) or frappe.db.get_value(
                    "Go1 FCloud Server", {"server_id": server}, "name"
                )
            if server_doc:
                cloud_server_name = frappe.db.get_value(
                    "Go1 FCloud Server", server_doc, "server_id"
                )
        if not cloud_server_name:
            # Try resolving from the bench doc's server link
            bench_doc = frappe.db.get_value(
                "Go1 FCloud Bench", {"id": bench_id}, ["server", "server_id"], as_dict=True
            ) or {}
            if bench_doc.get("server_id"):
                cloud_server_name = bench_doc["server_id"]

        # Verify bench is active
        bench = unwrap(cloud_post("press.api.bench.get", {"name": bench_id}))
        if not bench:
            return _err("Release Group not found on Frappe Cloud.")
        if bench.get("status") != "Active":
            return _err(
                f"Release Group is '{bench.get('status')}'. It must be Active to create a site."
            )

        # Auto-resolve cluster from bench if not provided
        if not cluster:
            cluster = (
                bench.get("cluster")
                or bench.get("region")
                or bench.get("server_region_info", {}).get("name")
                or None
            )
        # Fallback: fetch cluster from bench regions API
        if not cluster:
            try:
                regions = unwrap(
                    cloud_post("press.api.bench.regions", {"name": bench_id})
                ) or []
                if regions:
                    cluster = regions[0].get("name", "")
            except Exception:
                pass

        # Fetch apps available on the bench to validate and get correct names
        bench_apps = unwrap(
            cloud_post("press.api.bench.apps", {"name": bench_id})
        ) or []
        bench_app_names = {a.get("name", ""): a for a in bench_apps}
        frappe.log_error("create_site:bench_apps", json.dumps(bench_apps, default=str)[:3000])

        # Only include apps that exist on the bench (plain name strings)
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

        # Resolve plan — match by name or title, default to cheapest
        site_plans = unwrap(cloud_get("press.api.site.get_site_plans")) or []
        resolved_plan = None
        if plan:
            for p in site_plans:
                if p.get("name") == plan:
                    resolved_plan = plan
                    break
                if p.get("plan_title") == plan or str(p.get("name", "")) in plan:
                    resolved_plan = p.get("name")
                    break
            if not resolved_plan:
                resolved_plan = plan  # pass through as-is
        if not resolved_plan and site_plans:
            # Default to cheapest plan (lowest price_inr)
            cheapest = min(
                site_plans,
                key=lambda p: float(p.get("price_inr", 0) or 0),
            )
            resolved_plan = cheapest.get("name")

        if group_provided and cloud_server_name:
            # Dedicated server + specific bench: create Site doc directly
            # via press.api.client.insert to bypass press.api.site.new's
            # bench-matching logic which ignores the group we specify.
            site_doc = {
                "doctype": "Site",
                "subdomain": site_name,
                "domain": domain,
                "group": bench_id,
                "server": cloud_server_name,
                "cluster": cluster or "",
                "apps": [{"app": a} for a in app_list],
                "subscription_plan": resolved_plan or "",
                "version": bench.get("version", ""),
            }
            frappe.log_error("create_site:insert_payload", json.dumps(site_doc, default=str))
            result = cloud_post("press.api.client.insert", {"doc": site_doc})
            return _ok(unwrap(result))
        else:
            # Standard flow: server-only or group-only
            site_payload = {
                "name": site_name,
                "domain": domain,
                "apps": app_list,
                "group": bench_id,
                "cluster": cluster or "",
                "plan": resolved_plan or "",
                "share_details_consent": share_details_consent,
                "agree_region_laws": agree_region_laws,
            }
            if cloud_server_name and not group_provided:
                site_payload["server"] = cloud_server_name
                site_payload["version"] = bench.get("version", "")
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


def _build_login_redirect_url(result, site_name, redirect_to=None):
    """
    Build a login redirect URL from a Press API ``site.login`` response.

    Handles the three response shapes Press may return: a dict with
    ``sid``, a full URL string, or a bare SID string.  Returns None
    if the response cannot be parsed.

    Args:
        result:      The unwrapped Press API response
        site_name:   Fallback hostname when not present in the response
        redirect_to: Optional path to append as ``redirect-to`` query param
    """
    if isinstance(result, dict) and result.get("sid"):
        sid = result["sid"]
        site_host = result.get("site", site_name)
        url = f"https://{site_host}/api/method/login?sid={sid}"
    elif isinstance(result, str) and result:
        if result.startswith("http"):
            url = result
        else:
            url = f"https://{site_name}/api/method/login?sid={result}"
    else:
        return None

    if redirect_to:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}redirect-to={redirect_to}"

    return url


@frappe.whitelist()
def site_login(site_name, reason=None):
    """
    Login as Administrator on a site. Returns a one-time login URL.

    Instead of returning a SID directly (which can expire before the
    mobile browser loads it), we generate a short-lived token and cache
    the site name.  The returned URL points to ``site_login_redirect``
    which fetches a **fresh** SID at the moment the browser hits it.

    Args:
      site_name:  Go1 FCloud Site doc name or Frappe Cloud site name
      reason:     Optional reason for the login
    """
    try:
        _require_role()
        cloud_name = _resolve_site(site_name)

        token = frappe.generate_hash(length=32)
        cache_data = {"site": cloud_name}
        if reason:
            cache_data["reason"] = reason
        frappe.cache().set_value(
            f"login_token:{token}",
            cache_data,
            expires_in_sec=300,  # 5 minutes
        )

        login_url = (
            f"{frappe.utils.get_url()}/api/method/"
            f"go1_fcloud.mobile_api.site_login_redirect?token={token}"
        )

        return _ok({
            "login_url": login_url,
        })
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.site_login", frappe.get_traceback())
        return _err("Failed to generate login URL.")


@frappe.whitelist(allow_guest=True)
def site_login_redirect(token=None):
    """
    Browser-facing redirect endpoint for site login.

    Validates the one-time token, fetches a fresh SID from the Press
    API, and 302-redirects the browser to the target site immediately.
    The SID is as fresh as possible — its age is only the time the
    browser takes to follow the redirect.
    """
    try:
        if not token:
            frappe.respond_as_web_page(
                "Invalid Link",
                "No token was provided. Please request a new login link from the app.",
                http_status_code=400,
                indicator_color="red",
            )
            return

        cache_key = f"login_token:{token}"
        data = frappe.cache().get_value(cache_key)

        if not data:
            frappe.respond_as_web_page(
                "Link Expired",
                "This login link has already been used or has expired. "
                "Please request a new one from the app.",
                http_status_code=410,
                indicator_color="orange",
            )
            return

        # Single-use: delete immediately
        frappe.cache().delete_value(cache_key)

        site_name = data.get("site")
        if not site_name:
            frappe.respond_as_web_page(
                "Invalid Link",
                "The login link is malformed. Please request a new one from the app.",
                http_status_code=400,
                indicator_color="red",
            )
            return

        # Elevate to Administrator so cloud_post can read
        # Go1 FCloud Configuration credentials (Guest cannot).
        original_user = frappe.session.user
        try:
            frappe.set_user("Administrator")
            params = {"name": site_name}
            if data.get("reason"):
                params["reason"] = data["reason"]
            result = unwrap(cloud_post("press.api.site.login", params))
        finally:
            frappe.set_user(original_user)

        # Build redirect URL from the Press API response
        redirect_url = _build_login_redirect_url(result, site_name)
        if not redirect_url:
            frappe.respond_as_web_page(
                "Login Failed",
                "Could not create a login session for the site. "
                "Please request a new login link from the app.",
                http_status_code=502,
                indicator_color="red",
            )
            return

        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = redirect_url
    except Exception:
        frappe.log_error("mobile_api.site_login_redirect", frappe.get_traceback())
        frappe.respond_as_web_page(
            "Something Went Wrong",
            "An unexpected error occurred. Please request a new login link from the app.",
            http_status_code=500,
            indicator_color="red",
        )


@frappe.whitelist()
def setup_site(site_name):
    """
    Return a direct login URL that opens the site's setup wizard.

    Fetches a fresh SID from the Press API and builds a login URL
    pointing to the target site's ``/setup-wizard``.  The mobile app
    can open this URL directly in a WebView or external browser.

    Also returns a fallback redirect URL (via ``setup_site_redirect``)
    in case the direct URL's SID expires before the browser loads it.

    Args:
      site_name: Go1 FCloud Site doc name or Frappe Cloud site name
    """
    try:
        _require_role()
        cloud_name = _resolve_site(site_name)

        # Fetch a fresh SID and build the direct setup wizard URL
        result = unwrap(cloud_post("press.api.site.login", {"name": cloud_name}))
        setup_url = _build_login_redirect_url(
            result, cloud_name, redirect_to="/setup-wizard"
        )

        # Also generate a token-based fallback URL
        token = frappe.generate_hash(length=32)
        frappe.cache().set_value(
            f"setup_token:{token}",
            {"site": cloud_name},
            expires_in_sec=300,  # 5 minutes
        )
        fallback_url = (
            f"{frappe.utils.get_url()}/api/method/"
            f"go1_fcloud.mobile_api.setup_site_redirect?token={token}"
        )

        if not setup_url:
            return _ok({"setup_wizard_url": fallback_url})

        return _ok({
            "setup_wizard_url": setup_url,
            "fallback_url": fallback_url,
        })
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.setup_site", frappe.get_traceback())
        return _err("Failed to generate setup wizard URL.")


@frappe.whitelist(allow_guest=True)
def setup_site_redirect(token=None):
    """
    Browser-facing redirect endpoint.

    Validates the one-time token, fetches a fresh SID from the Press
    API, and 302-redirects the browser to the site's setup wizard
    immediately.  The SID is as fresh as possible — its age is only
    the time the browser takes to follow the redirect.
    """
    try:
        if not token:
            frappe.respond_as_web_page(
                "Invalid Link",
                "No token was provided. Please request a new setup link from the app.",
                http_status_code=400,
                indicator_color="red",
            )
            return

        cache_key = f"setup_token:{token}"
        data = frappe.cache().get_value(cache_key)

        if not data:
            frappe.respond_as_web_page(
                "Link Expired",
                "This setup link has already been used or has expired. "
                "Please request a new one from the app.",
                http_status_code=410,
                indicator_color="orange",
            )
            return

        # Single-use: delete immediately
        frappe.cache().delete_value(cache_key)

        site_name = data.get("site")
        if not site_name:
            frappe.respond_as_web_page(
                "Invalid Link",
                "The setup link is malformed. Please request a new one from the app.",
                http_status_code=400,
                indicator_color="red",
            )
            return

        # Elevate to Administrator so cloud_post can read
        # Go1 FCloud Configuration credentials (Guest cannot).
        original_user = frappe.session.user
        try:
            frappe.set_user("Administrator")
            result = unwrap(cloud_post("press.api.site.login", {"name": site_name}))
        finally:
            frappe.set_user(original_user)

        # Build redirect URL from the Press API response
        redirect_url = _build_login_redirect_url(
            result, site_name, redirect_to="/setup-wizard"
        )
        if not redirect_url:
            frappe.respond_as_web_page(
                "Setup Failed",
                "Could not create a login session for the site. "
                "Please request a new setup link from the app.",
                http_status_code=502,
                indicator_color="red",
            )
            return

        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = redirect_url
    except Exception:
        frappe.log_error("mobile_api.setup_site_redirect", frappe.get_traceback())
        frappe.respond_as_web_page(
            "Something Went Wrong",
            "An unexpected error occurred. Please request a new setup link from the app.",
            http_status_code=500,
            indicator_color="red",
        )


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
def get_job_detail(job_name):
    """
    Return full detail for a single job, including its steps.

    Args:
      job_name:  The Agent Job name / ID (e.g. "asinrt97k7")

    Response:
      name, job_type, status, creation, creator, start, end, duration,
      steps: [{name, step_name, status, start, end, duration}, ...]
    """
    try:
        _require_role()

        if not job_name:
            return _err("job_name is required.")

        # Fetch full Agent Job document via press.api.client.get
        job = unwrap(
            cloud_post(
                "press.api.client.get",
                {"doctype": "Agent Job", "name": job_name},
            )
        ) or {}

        steps_raw = job.get("steps", [])
        steps = []
        for s in steps_raw:
            step_start = s.get("start") or ""
            step_end = s.get("end") or ""
            step_duration = s.get("duration") or ""
            if not step_duration and step_start and step_end:
                try:
                    diff = frappe.utils.time_diff_in_seconds(step_end, step_start)
                    step_duration = f"{int(diff)}s"
                except Exception:
                    step_duration = ""
            steps.append({
                "name": s.get("name", ""),
                "step_name": s.get("step_name", ""),
                "status": s.get("status", ""),
                "start": step_start,
                "end": step_end,
                "duration": step_duration,
                "output": s.get("output", ""),
                "command": s.get("command", ""),
                "traceback": s.get("traceback", ""),
            })

        job_start = job.get("start") or ""
        job_end = job.get("end") or ""
        job_duration = job.get("duration") or ""
        if not job_duration and job_start and job_end:
            try:
                diff = frappe.utils.time_diff_in_seconds(job_end, job_start)
                job_duration = f"{int(diff)}s"
            except Exception:
                job_duration = ""

        return _ok({
            "name": job.get("name", job_name),
            "job_type": job.get("job_type", ""),
            "status": job.get("status", ""),
            "creation": job.get("creation", ""),
            "creator": job.get("owner", ""),
            "start": job_start,
            "end": job_end,
            "duration": job_duration,
            "steps": steps,
        })
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.get_job_detail", frappe.get_traceback())
        return _err("Failed to fetch job detail.")


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
def get_benches(status_filter=None, search=None, server=None, start=0, limit=20):
    """
    List benches from local Go1 FCloud Bench doctype with permission checks.

    Uses ``frappe.get_list`` which automatically enforces the Role Permission
    Manager rules defined on Go1 FCloud Bench (System Manager, FCloud,
    FCloud Admin).

    Args:
      status_filter: "Active" | "Awaiting Deploy" | "Update Available" | None (all)
      search:        substring search on bench title or id
      server:        filter by Go1 FCloud Server link
      start:         pagination offset (default 0)
      limit:         page size (default 20)
    """
    try:
        start = frappe.utils.cint(start)
        limit = frappe.utils.cint(limit) or 20

        # Permission flags for the current user
        can_read = frappe.has_permission("Go1 FCloud Bench", "read")
        can_create = frappe.has_permission("Go1 FCloud Bench", "create")
        can_write = frappe.has_permission("Go1 FCloud Bench", "write")
        can_delete = frappe.has_permission("Go1 FCloud Bench", "delete")

        if not can_read:
            return _err("Not permitted to access Go1 FCloud Bench.")

        # Build filters — frappe.get_list applies permission checks automatically
        filters = {"is_dropped": 0}
        if status_filter:
            filters["status"] = status_filter
        if server:
            # Resolve server: accept doc name, server_name (title), or server_id
            if not frappe.db.exists("Go1 FCloud Server", server):
                server = frappe.db.get_value(
                    "Go1 FCloud Server",
                    {"server_name": server},
                    "name",
                ) or frappe.db.get_value(
                    "Go1 FCloud Server",
                    {"server_id": server},
                    "name",
                ) or server
            filters["server"] = server
        if search:
            filters["bench"] = ("like", f"%{search}%")

        # Status counts (across all benches, before pagination/filters)
        all_benches = frappe.get_list(
            "Go1 FCloud Bench",
            filters={"is_dropped": 0},
            fields=["status"],
            ignore_ifnull=True,
        )
        status_counts = {}
        for b in all_benches:
            st = b.get("status") or ""
            status_counts[st] = status_counts.get(st, 0) + 1

        total = len(all_benches)
        active_count = status_counts.get("Active", 0)
        awaiting_deploy_count = status_counts.get("Awaiting Deploy", 0)
        update_available_count = status_counts.get("Update Available", 0)

        # Filtered + paginated bench list
        bench_records = frappe.get_list(
            "Go1 FCloud Bench",
            filters=filters,
            fields=[
                "name", "bench", "id", "status", "version",
                "region", "server", "project", "noof_apps",
                "creation", "modified",
            ],
            order_by="modified desc",
            start=start,
            page_length=limit,
            ignore_ifnull=True,
        )

        # Total count for the current filter set (for pagination)
        total_filtered = frappe.db.count(
            "Go1 FCloud Bench", filters=filters
        )
        has_next = (start + limit) < total_filtered

        # Collect unique servers for filter dropdown (with display names)
        server_link_names = frappe.get_list(
            "Go1 FCloud Bench",
            filters={"is_dropped": 0, "server": ("is", "set")},
            fields=["distinct server as server"],
            ignore_ifnull=True,
        )
        server_names = [s["server"] for s in server_link_names if s.get("server")]
        servers = []
        for sn in sorted(server_names):
            title = frappe.db.get_value("Go1 FCloud Server", sn, "server_name") or sn
            servers.append({"name": sn, "title": title})

        # Build response
        benches = []
        for b in bench_records:
            # Fetch apps from child table
            apps = frappe.get_all(
                "Apps",
                filters={"parent": b["name"], "parenttype": "Go1 FCloud Bench"},
                fields=["title"],
            )
            app_names = [a["title"] for a in apps if a.get("title")]

            server_doc_name = b.get("server", "")
            server_title = (
                frappe.db.get_value("Go1 FCloud Server", server_doc_name, "server_name")
                if server_doc_name else ""
            ) or server_doc_name

            benches.append({
                "name": b.get("name", ""),
                "bench_id": b.get("id", ""),
                "title": b.get("bench", ""),
                "status": b.get("status", ""),
                "version": b.get("version", ""),
                "region": b.get("region", ""),
                "server": server_doc_name,
                "server_title": server_title,
                "project": b.get("project", ""),
                "creation": b.get("creation", ""),
                "modified": b.get("modified", ""),
                "app_count": b.get("noof_apps") or len(app_names),
                "apps": app_names,
            })

        return _ok({
            "permissions": {
                "can_read": can_read,
                "can_create": can_create,
                "can_write": can_write,
                "can_delete": can_delete,
            },
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
            "servers": servers,
            "benches": benches,
            "total_filtered": total_filtered,
            "start": start,
            "limit": limit,
            "has_next": has_next,
        })
    except frappe.PermissionError:
        return _err("Not permitted to access Go1 FCloud Bench.")
    except Exception:
        frappe.log_error("mobile_api.get_benches", frappe.get_traceback())
        return _err("Failed to fetch benches.")


@frappe.whitelist()
def get_bench(name):
    """Return full bench details fetched live from Frappe Cloud."""
    try:
        if not frappe.has_permission("Go1 FCloud Bench", "read"):
            return _err("Not permitted to access Go1 FCloud Bench.")
        doc, bench_id = _resolve_bench(name)

        # Fetch bench info live from Frappe Cloud
        bench_data = (
            unwrap(cloud_post("press.api.bench.get", {"name": bench_id})) or {}
        )

        # Fetch apps live from Frappe Cloud
        cloud_apps = (
            unwrap(cloud_post("press.api.bench.apps", {"name": bench_id})) or []
        )

        # Fetch app images from Marketplace App
        app_names = [a.get("name", "") for a in cloud_apps if a.get("name")]
        app_image_map = {}
        if app_names:
            marketplace_apps = (
                unwrap(
                    cloud_post(
                        "press.api.client.get_list",
                        {
                            "doctype": "Marketplace App",
                            "fields": ["name", "app", "image"],
                            "filters": {"app": ["in", app_names]},
                            "limit_page_length": len(app_names),
                        },
                    )
                )
                or []
            )
            for ma in marketplace_apps:
                app_image_map[ma.get("app", "")] = ma.get("image", "")

        apps = [
            {
                "name": a.get("name", ""),
                "title": a.get("title", ""),
                "branch": a.get("branch", ""),
                "image": app_image_map.get(a.get("name", ""), ""),
            }
            for a in cloud_apps
        ]

        # Check if updates are available
        deploy_info = _fetch_deploy_information(bench_id) or {}
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

        # Fetch sites on this bench from local Go1 FCloud Site docs
        bench_doc_name = doc.name if doc else ""
        local_site_filters = {"is_dropped": 0}
        if bench_doc_name:
            local_site_filters["bench_name"] = bench_doc_name
        else:
            local_site_filters["group"] = bench_id
        site_records = frappe.get_list(
            "Go1 FCloud Site",
            filters=local_site_filters,
            fields=["name", "site_name", "url", "status"],
            order_by="modified desc",
        )
        bench_sites = [
            {
                "name": s.get("name", ""),
                "site_name": s.get("url", "") or s.get("site_name", ""),
                "title": s.get("site_name", ""),
                "status": s.get("status", ""),
            }
            for s in site_records
        ]

        # Region info
        region = bench_data.get("cluster", "")
        cluster_image = bench_data.get("cluster_image", "") or bench_data.get("image", "")

        # Server info from local doc
        server_doc_name = doc.server if doc else ""
        server_title = ""
        server_id = doc.server_id if doc else ""
        if server_doc_name:
            server_title = (
                frappe.db.get_value("Go1 FCloud Server", server_doc_name, "server_name")
                or server_doc_name
            )

        return _ok(
            {
                "name": doc.name if doc else "",
                "bench": bench_data.get("title", doc.bench if doc else ""),
                "bench_id": bench_id,
                "status": bench_data.get("status", ""),
                "version": bench_data.get("version", ""),
                "region": region,
                "region_image": cluster_image,
                "creation": bench_data.get("creation", ""),
                "project": doc.project if doc else "",
                "server": server_doc_name,
                "server_title": server_title,
                "server_id": server_id,
                "update_available": update_available,
                "apps": apps,
                "sites": bench_sites,
                "site_count": len(bench_sites),
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
              deploy_check | stop_deploy | remove_app | change_branch |
              generate_ssh_key
      extra:  JSON string with optional params
              stop_deploy:   {"candidate": "pipeline-name"} (optional — stops latest if omitted)
              remove_app:    {"app": "erpnext"}
              change_branch: {"app": "erpnext", "to_branch": "version-15"}
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
            info = _fetch_deploy_information(bench_id)
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

        elif action == "change_branch":
            params = json.loads(extra) if extra else {}
            app = params.get("app", "")
            to_branch = params.get("to_branch", "")
            if not app or not to_branch:
                return _err("App and to_branch are required. Pass extra: {\"app\": \"erpnext\", \"to_branch\": \"version-15\"}")
            result = cloud_post(
                "press.api.bench.change_branch",
                {"name": bench_id, "app": app, "to_branch": to_branch},
            )
            return _ok(unwrap(result))

        elif action == "stop_deploy":
            params = json.loads(extra) if isinstance(extra, str) and extra else {}
            candidate = params.get("candidate", "")
            return _stop_bench_deploy(bench_id, candidate)

        elif action == "generate_ssh_key":
            # Try to get an existing valid certificate first
            cert = unwrap(
                cloud_post(
                    "press.api.client.run_doc_method",
                    {
                        "dt": "Release Group",
                        "dn": bench_id,
                        "method": "get_certificate",
                    },
                )
            )
            # If no valid certificate exists, generate a new one
            if not cert:
                cert = unwrap(
                    cloud_post(
                        "press.api.bench.generate_certificate",
                        {"name": bench_id},
                    )
                )
            if not cert or not cert.get("ssh_certificate"):
                return _err("Failed to generate SSH certificate.")

            ssh_certificate = cert["ssh_certificate"]

            # Build SSH command from bench versions and site info
            versions = (
                unwrap(cloud_post("press.api.bench.versions", {"name": bench_id}))
                or []
            )
            site_bench_resp = (
                unwrap(
                    cloud_post(
                        "press.api.client.get_list",
                        {
                            "doctype": "Site",
                            "fields": ["bench"],
                            "filters": {
                                "group": bench_id,
                                "skip_team_filter_for_system_user": True,
                            },
                            "order_by": "creation desc, bench desc",
                            "limit_page_length": 1,
                        },
                    )
                )
                or []
            )
            if not versions or not site_bench_resp:
                return _err("Could not build SSH command. Is there a site on this bench?")

            site_bench = site_bench_resp[0].get("bench", "")
            proxy = versions[0].get("proxy_server", "")
            ssh_command = f"ssh {site_bench}@{proxy} -p 2222"
            step1 = f"echo '{ssh_certificate.strip()}' > ~/.ssh/id_rsa-cert.pub"
            full_command = f"{step1} && {ssh_command}"

            if doc:
                doc.ssh_certificate = ssh_certificate
                doc.command = ssh_command
                doc.save(ignore_permissions=True)

            return _ok({
                "certificate": cert,
                "ssh_command": ssh_command,
                "command": full_command,
            })

        else:
            return _err(
                f"Unknown action: {action}. Valid: restart, rebuild, update_all_sites, archive, deploy_check, stop_deploy, remove_app, change_branch, generate_ssh_key"
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
def stop_deploy(name, candidate=None):
    """
    Stop / cancel an active deploy for a bench.

    Args:
      name:       Go1 FCloud Bench doc name, cloud bench ID, or bench title
      candidate:  Specific Release Pipeline or Deploy Candidate name to cancel.
                  If omitted, cancels the most recent running deploy.
    """
    try:
        _require_role()
        _, bench_id = _resolve_bench(name)
        return _stop_bench_deploy(bench_id, candidate)
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.stop_deploy", frappe.get_traceback())
        return _err("Failed to stop deploy.")


def _stop_bench_deploy(bench_id, candidate=None):
    """Shared helper to stop a deploy for a bench (used by bench_action and stop_deploy)."""

    # Fetch deploy_information (separate endpoint from bench.get)
    # Returns: last_deploy (Deploy Candidate Build: name, status, creation),
    #          deploy_in_progress, has_running_release_pipeline
    try:
        deploy_info = unwrap(
            cloud_post("press.api.bench.deploy_information", {"name": bench_id})
        ) or {}

        last_dc = deploy_info.get("last_deploy") or {}
        dc_build_name = last_dc.get("name", "")
        dc_status = last_dc.get("status", "")
        deploy_in_progress = deploy_info.get("deploy_in_progress", False)

        frappe.log_error(
            "stop_deploy:deploy_info",
            json.dumps({
                "bench_id": bench_id, "candidate_param": candidate,
                "last_deploy": last_dc, "deploy_in_progress": deploy_in_progress,
                "has_running_pipeline": deploy_info.get("has_running_release_pipeline"),
            }, default=str)[:3000],
        )

        if not deploy_in_progress:
            # Clear error messages
            if hasattr(frappe.local, "message_log"):
                frappe.local.message_log = []
            return _err("No active deploy in progress.")

        # The last_deploy.name is a Deploy Candidate Build name.
        # fail_build expects a Deploy Candidate name (the parent).
        # Try using the build name directly with fail_build first,
        # then try the caller's candidate.
        names_to_try = []
        if dc_build_name:
            names_to_try.append(dc_build_name)
        if candidate and candidate not in names_to_try:
            names_to_try.append(candidate)

        for dn in names_to_try:
            result = _cancel_deploy_candidate(bench_id, dn)
            if result:
                return _ok(result)

    except Exception:
        frappe.log_error("stop_deploy:fetch_info", frappe.get_traceback())
        # Fallback: try with caller's candidate directly
        if candidate:
            result = _cancel_deploy_candidate(bench_id, candidate)
            if result:
                return _ok(result)

    # Clear accumulated error messages from failed attempts
    if hasattr(frappe.local, "message_log"):
        frappe.local.message_log = []

    return _err(f"Could not stop deploy for bench '{bench_id}'. Check error log for details.")


def _cancel_deploy_candidate(bench_id, candidate_name):
    """Cancel a deploy by name. Tries multiple Press API approaches."""
    def _clear_msg_log():
        if hasattr(frappe.local, "message_log"):
            frappe.local.message_log = []

    # 1. Try press.api.bench.fail_build (stops a running build job)
    try:
        result = unwrap(
            cloud_post(
                "press.api.bench.fail_build",
                {"name": bench_id, "dn": candidate_name},
            )
        )
        return {
            "candidate": candidate_name,
            "status": "Cancelled",
            "method": "fail_build",
            "result": result,
        }
    except Exception:
        _clear_msg_log()

    # 2. Try press.api.bench.fail_and_redeploy
    try:
        result = unwrap(
            cloud_post(
                "press.api.bench.fail_and_redeploy",
                {"name": bench_id, "dc_name": candidate_name},
            )
        )
        return {
            "candidate": candidate_name,
            "status": "Cancelled",
            "method": "fail_and_redeploy",
            "result": result,
        }
    except Exception:
        _clear_msg_log()

    # 3. Try press.api.client.run_doc_method
    for doctype in ("Deploy Candidate", "Deploy Candidate Build"):
        try:
            result = unwrap(
                cloud_post(
                    "press.api.client.run_doc_method",
                    {"dt": doctype, "dn": candidate_name, "method": "fail"},
                )
            )
            return {
                "candidate": candidate_name,
                "doctype": doctype,
                "status": "Cancelled",
                "method": "run_doc_method",
                "result": result,
            }
        except Exception:
            _clear_msg_log()
            continue

    return None


@frappe.whitelist()
def get_bench_jobs(name):
    """
    Return running and recent jobs for a bench.

    Args:
      name:  Go1 FCloud Bench doc name, Cloud bench ID, or title
    """
    try:
        _require_role()
        doc, bench_id = _resolve_bench(name)

        running = (
            unwrap(cloud_post("press.api.bench.running_jobs", {"name": bench_id}))
            or []
        )

        recent = (
            unwrap(
                cloud_post(
                    "press.api.bench.jobs",
                    {
                        "filters": {"name": bench_id},
                        "order_by": "creation desc",
                        "limit_page_length": 20,
                    },
                )
            )
            or []
        )

        return _ok({"running": running, "recent": recent})
    except Exception:
        frappe.log_error("mobile_api.get_bench_jobs", frappe.get_traceback())
        return _err("Failed to fetch bench jobs.")


@frappe.whitelist()
def get_bench_dependencies(name):
    """
    Return active and supported dependencies for a bench (e.g. Node.js, Python versions).

    Args:
      name:  Go1 FCloud Bench doc name, Cloud bench ID, or title
    """
    try:
        _require_role()
        doc, bench_id = _resolve_bench(name)
        result = cloud_post("press.api.bench.dependencies", {"name": bench_id})
        return _ok(unwrap(result))
    except Exception:
        frappe.log_error("mobile_api.get_bench_dependencies", frappe.get_traceback())
        return _err("Failed to fetch bench dependencies.")


@frappe.whitelist(methods=["POST"])
def update_bench_dependencies(name, dependencies=None):
    """
    Update dependencies (e.g. Node.js, Python versions) for a bench.

    Args:
      name:          Go1 FCloud Bench doc name, Cloud bench ID, or title
      dependencies:  list of {"key": ..., "value": ...} dicts, or a JSON string
    """
    try:
        _require_role()
        doc, bench_id = _resolve_bench(name)

        if isinstance(dependencies, str):
            dependencies = json.loads(dependencies)

        result = cloud_post(
            "press.api.bench.update_dependencies",
            {"name": bench_id, "dependencies": json.dumps(dependencies)},
        )
        return _ok(unwrap(result))
    except Exception:
        frappe.log_error("mobile_api.update_bench_dependencies", frappe.get_traceback())
        return _err("Failed to update bench dependencies.")


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
        info = _fetch_deploy_information(bench_id)
        if not info:
            return _err("Could not fetch deploy information.")

        if info.get("deploy_in_progress"):
            return _err("A deploy is already in progress for this bench.")

        # Press validate_app_hashes requires EVERY app to have both
        # "release" and "hash".  deploy_information returns each app's
        # releases list (with name + hash per entry) and current_hash /
        # current_release for the deployed version.  We must look up the
        # hash from the releases list when a specific release is chosen.
        all_apps = info.get("apps", [])
        user_app_map = {a.get("app"): a for a in apps} if apps else {}

        apps_to_deploy = []
        for ia in all_apps:
            app_name = ia.get("app", "")
            ua = user_app_map.get(app_name)

            # Build a release-name → hash lookup from the releases list
            releases = ia.get("releases") or []
            release_hash_map = {
                r.get("name"): r.get("hash", "")
                for r in releases
                if r.get("name")
            }

            if ua:
                # User selected this app — use their release
                release = ua.get("release") or ia.get("next_release", "")
                hash_val = (
                    ua.get("hash")
                    or release_hash_map.get(release, "")
                    or ia.get("current_hash", "")
                )
            else:
                # Not selected — keep current; fall back to next for
                # newly added apps that have no current release yet.
                release = ia.get("current_release") or ia.get("next_release", "")
                hash_val = (
                    ia.get("current_hash")
                    or release_hash_map.get(release, "")
                )

            if not release or not hash_val:
                continue

            apps_to_deploy.append({
                "app": app_name,
                "source": ia.get("source", ""),
                "release": release,
                "hash": hash_val,
            })

        if not apps_to_deploy:
            return _err("No updates available to deploy.")

        # Build sites payload — enrich user-provided sites with server
        # and bench from deploy_information so Press can match them.
        if sites:
            info_sites = info.get("sites", [])
            info_site_map = {s.get("name"): s for s in info_sites}

            sites_to_update = []
            for us in sites:
                site_name = us.get("name", "")
                is_ = info_site_map.get(site_name, {})
                sites_to_update.append({
                    "name": site_name,
                    "server": us.get("server") or is_.get("server", ""),
                    "bench": us.get("bench") or is_.get("bench", ""),
                    "skip_failing_patches": us.get("skip_failing_patches", False),
                    "skip_backups": us.get("skip_backups", False),
                })

            result = cloud_post(
                "press.api.bench.deploy_and_update",
                {
                    "name": bench_id,
                    "apps": apps_to_deploy,
                    "sites": sites_to_update,
                    "run_will_fail_check": True,
                },
            )
        else:
            result = cloud_post(
                "press.api.bench.deploy",
                {
                    "name": bench_id,
                    "apps": apps_to_deploy,
                    "run_will_fail_check": True,
                },
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
        if not frappe.has_permission("Go1 FCloud Bench", "read"):
            return _err("Not permitted to access Go1 FCloud Bench.")
        doc, bench_id = _resolve_bench(name)

        info = _fetch_deploy_information(bench_id) or {}

        apps = []
        for app in info.get("apps", []):
            apps.append(
                {
                    "name": app.get("app", ""),
                    "title": app.get("title", ""),
                    "source": app.get("source", ""),
                    "branch": app.get("branch", ""),
                    "repository": app.get("repository", ""),
                    "repository_owner": app.get("repository_owner", ""),
                    "current_hash": app.get("current_hash", ""),
                    "current_tag": app.get("current_tag", ""),
                    "current_release": app.get("current_release", ""),
                    "next_release": app.get("next_release", ""),
                    "releases": [
                        {
                            "name": r.get("name", ""),
                            "hash": r.get("hash", ""),
                            "tag": r.get("tag", ""),
                        }
                        for r in (app.get("releases") or [])
                    ],
                    "update_available": app.get("update_available", False),
                    "will_branch_change": app.get("will_branch_change", False),
                }
            )

        # Fetch sites from local Go1 FCloud Site docs instead of cloud API
        bench_doc_name = doc.name if doc else ""
        site_filters = {"is_dropped": 0}
        if bench_doc_name:
            site_filters["bench_name"] = bench_doc_name
        else:
            site_filters["group"] = bench_id
        site_records = frappe.get_list(
            "Go1 FCloud Site",
            filters=site_filters,
            fields=["name", "site_name", "url", "status", "bench"],
            order_by="modified desc",
        )
        sites = [
            {
                "name": s.get("url", "") or s.get("site_name", ""),
                "site_name": s.get("url", "") or s.get("site_name", ""),
                "title": s.get("site_name", ""),
                "status": s.get("status", ""),
                "server": s.get("bench", ""),
                "bench": bench_doc_name,
                "skip_failing_patches": False,
                "skip_backups": False,
            }
            for s in site_records
        ]

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
def get_bench_deploys(name, start=0, limit=20):
    """
    Return deploy history for a bench including failed deploys.

    Fetches Release Pipeline records via press.api.client.get_list
    with pagination support.

    Args:
      name:   Go1 FCloud Bench doc name or Frappe Cloud bench ID
      start:  Pagination offset (default 0)
      limit:  Page size (default 20)
    """
    try:
        _require_role()
        doc, bench_id = _resolve_bench(name)

        start = frappe.utils.cint(start)
        limit = frappe.utils.cint(limit) or 20

        # Fetch deploy pipelines (includes Success, Failure, Running, etc.)
        pipelines = (
            unwrap(
                cloud_post(
                    "press.api.client.get_list",
                    {
                        "doctype": "Release Pipeline",
                        "filters": {"release_group": bench_id},
                        "fields": ["name", "status", "creation", "owner"],
                        "order_by": "creation desc",
                        "start": start,
                        "limit": limit,
                        "limit_start": start,
                        "limit_page_length": limit,
                    },
                )
            )
            or []
        )

        # Fetch current deploy information
        deploy_info = _fetch_deploy_information(bench_id) or {}

        deploys = []
        for p in pipelines:
            deploys.append({
                "name": p.get("name", ""),
                "status": p.get("status", ""),
                "creation": p.get("creation", ""),
                "owner": p.get("owner", ""),
            })

        return _ok({
            "deploys": deploys,
            "deploy_in_progress": deploy_info.get("deploy_in_progress", False),
            "update_available": any(
                a.get("update_available") for a in deploy_info.get("apps", [])
            ),
            "start": start,
            "limit": limit,
        })
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.get_bench_deploys", frappe.get_traceback())
        return _err("Failed to fetch bench deploy history.")


@frappe.whitelist()
def get_bench_deploy_candidate(candidate_name=None, name=None):
    """
    Return deploy pipeline / build detail for a specific deploy.

    Shows: status, created_by, start/end times, duration, build stages
    with steps (command, output, cached flag), issues, and build output.

    The ``candidate_name`` (or ``name``) can be:
      - A Release Pipeline name  (newer deploys)
      - A Deploy Candidate Build name
      - A Deploy Candidate name  (resolved to its builds)

    Args:
      candidate_name:  Pipeline, build, or deploy-candidate identifier
                       (e.g. "734h2vihje")
      name:            Alias for candidate_name (for mobile app compat)
    """
    try:
        _require_role()
        candidate_name = candidate_name or name
        if not candidate_name:
            return _err("Missing required parameter: candidate_name or name.")

        pipeline = None
        builds = []

        # 1. Try as Release Pipeline (newer deploy system)
        try:
            pipeline = unwrap(
                cloud_post(
                    "press.api.client.get",
                    {"doctype": "Release Pipeline", "name": candidate_name},
                )
            )
        except Exception:
            frappe.clear_messages()

        if pipeline:
            # Extract build names from every known child-table / field shape
            build_names = []

            # a) pipeline_builds child table (field "build" or "deploy_candidate_build")
            for pb in pipeline.get("pipeline_builds", []):
                if isinstance(pb, dict):
                    bname = (
                        pb.get("build")
                        or pb.get("deploy_candidate_build")
                        or pb.get("name")
                    )
                    if bname and bname not in build_names:
                        build_names.append(bname)

            # b) steps list — may contain nested builds
            for stage in pipeline.get("steps", []):
                if not isinstance(stage, dict):
                    continue
                for b in stage.get("builds", []):
                    if isinstance(b, dict):
                        bname = b.get("name") or b.get("build")
                        if bname and bname not in build_names:
                            build_names.append(bname)

            # c) Direct link fields on the pipeline document
            for field in ("intel_build", "arm_build", "build", "deploy_candidate"):
                bname = pipeline.get(field)
                if bname and bname not in build_names:
                    build_names.append(bname)

            # d) If still empty, query Deploy Candidate Builds linked to this pipeline
            if not build_names:
                try:
                    linked_builds = unwrap(
                        cloud_post(
                            "press.api.client.get_list",
                            {
                                "doctype": "Deploy Candidate Build",
                                "filters": {"release_pipeline": candidate_name},
                                "fields": ["name"],
                                "limit_page_length": 20,
                            },
                        )
                    ) or []
                    for lb in linked_builds:
                        bname = lb.get("name")
                        if bname and bname not in build_names:
                            build_names.append(bname)
                except Exception:
                    frappe.clear_messages()

            # e) If still empty, try via Deploy Candidate linked to the pipeline
            if not build_names:
                try:
                    linked_dcs = unwrap(
                        cloud_post(
                            "press.api.client.get_list",
                            {
                                "doctype": "Deploy Candidate",
                                "filters": {"release_pipeline": candidate_name},
                                "fields": ["name", "intel_build", "arm_build"],
                                "limit_page_length": 20,
                            },
                        )
                    ) or []
                    for dc in linked_dcs:
                        for bf in ("intel_build", "arm_build"):
                            bname = dc.get(bf)
                            if bname and bname not in build_names:
                                build_names.append(bname)
                except Exception:
                    frappe.clear_messages()

            # Fetch each build's detail
            for bname in build_names:
                try:
                    build_doc = unwrap(
                        cloud_post(
                            "press.api.client.get",
                            {"doctype": "Deploy Candidate Build", "name": bname},
                        )
                    )
                    if build_doc and isinstance(build_doc, dict):
                        builds.append(_format_build(build_doc))
                except Exception:
                    frappe.clear_messages()

            return _ok({
                "type": "pipeline",
                "name": pipeline.get("name", ""),
                "status": pipeline.get("status", ""),
                "creation": pipeline.get("creation", ""),
                "owner": pipeline.get("owner", ""),
                "release_group": pipeline.get("release_group", ""),
                "builds": builds,
            })

        # 2. Try as Deploy Candidate Build
        build_doc = None
        try:
            build_doc = unwrap(
                cloud_post(
                    "press.api.client.get",
                    {"doctype": "Deploy Candidate Build", "name": candidate_name},
                )
            )
        except Exception:
            frappe.clear_messages()

        if build_doc:
            return _ok({
                "type": "build",
                **_format_build(build_doc),
            })

        # 3. Try as Deploy Candidate — fetch its linked builds
        dc_doc = None
        try:
            dc_doc = unwrap(
                cloud_post(
                    "press.api.client.get",
                    {"doctype": "Deploy Candidate", "name": candidate_name},
                )
            )
        except Exception:
            frappe.clear_messages()

        if dc_doc:
            # Fetch builds linked to this deploy candidate
            for field in ("intel_build", "arm_build"):
                bname = dc_doc.get(field)
                if bname:
                    try:
                        b = unwrap(
                            cloud_post(
                                "press.api.client.get",
                                {"doctype": "Deploy Candidate Build", "name": bname},
                            )
                        )
                        if b:
                            builds.append(_format_build(b))
                    except Exception:
                        frappe.clear_messages()

            return _ok({
                "type": "deploy_candidate",
                "name": dc_doc.get("name", ""),
                "group": dc_doc.get("group", ""),
                "creation": dc_doc.get("creation", ""),
                "owner": dc_doc.get("owner", ""),
                "apps": dc_doc.get("apps", []),
                "builds": builds,
            })

        # 4. Last resort — try the protected endpoint
        try:
            result = unwrap(
                cloud_get(
                    "press.api.bench.candidate", {"name": candidate_name}
                )
            )
            return _ok(result)
        except Exception:
            frappe.clear_messages()

        return _err(f"Deploy '{candidate_name}' not found.")
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error(
            "mobile_api.get_bench_deploy_candidate", frappe.get_traceback()
        )
        return _err("Failed to fetch deploy candidate status.")


def _format_build(build_doc):
    """Format a Deploy Candidate Build document for the mobile API response."""
    build_steps = build_doc.get("build_steps", [])
    # Group steps by stage
    stages = {}
    for step in build_steps:
        stage_name = step.get("stage", "Unknown")
        if stage_name not in stages:
            stages[stage_name] = {
                "stage": stage_name,
                "stage_slug": step.get("stage_slug", ""),
                "status": "Pending",
                "steps": [],
                "duration": 0,
            }
        stages[stage_name]["steps"].append({
            "step": step.get("step", ""),
            "step_slug": step.get("step_slug", ""),
            "status": step.get("status", "Pending"),
            "duration": step.get("duration", 0),
            "cached": step.get("cached", False),
            "command": step.get("command", ""),
            "output": step.get("output", ""),
        })
        stages[stage_name]["duration"] += float(step.get("duration") or 0)
        # Stage status = worst status among its steps
        step_status = step.get("status", "Pending")
        if step_status == "Failure":
            stages[stage_name]["status"] = "Failure"
        elif step_status == "Running" and stages[stage_name]["status"] != "Failure":
            stages[stage_name]["status"] = "Running"
        elif step_status == "Success" and stages[stage_name]["status"] == "Pending":
            stages[stage_name]["status"] = "Success"

    return {
        "name": build_doc.get("name", ""),
        "status": build_doc.get("status", ""),
        "platform": build_doc.get("platform", ""),
        "creation": build_doc.get("creation", ""),
        "owner": build_doc.get("owner", ""),
        "build_start": build_doc.get("build_start", ""),
        "build_end": build_doc.get("build_end", ""),
        "build_duration": build_doc.get("build_duration", ""),
        "build_error": build_doc.get("build_error", ""),
        "build_output": build_doc.get("build_output", ""),
        "deploy_candidate": build_doc.get("deploy_candidate", ""),
        "group": build_doc.get("group", ""),
        "stages": list(stages.values()),
    }


@frappe.whitelist()
def get_app_branch_list(name, app):
    """
    Return available git branches for an app on a bench.

    Args:
      name:  Go1 FCloud Bench doc name, Cloud bench ID, or bench title
      app:   App name (e.g. "erpnext")
    """
    try:
        _require_role()
        doc, bench_id = _resolve_bench(name)
        result = unwrap(
            cloud_get(
                "press.api.bench.branch_list",
                {"name": bench_id, "app": app},
            )
        )
        return _ok(result)
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.get_app_branch_list", frappe.get_traceback())
        return _err("Failed to fetch branch list.")


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
def get_servers(status_filter=None, search=None, start=0, limit=20):
    """
    List servers from local Go1 FCloud Server doctype with permission checks.

    Uses ``frappe.get_list`` which automatically enforces the Role Permission
    Manager rules defined on Go1 FCloud Server (System Manager, FCloud,
    FCloud Admin).

    Args:
      status_filter: "Active" | "Pending" | None (all)
      search:        substring search on server name
      start:         pagination offset (default 0)
      limit:         page size (default 20)
    """
    try:
        start = frappe.utils.cint(start)
        limit = frappe.utils.cint(limit) or 20

        # Permission flags for the current user
        can_read = frappe.has_permission("Go1 FCloud Server", "read")
        can_create = frappe.has_permission("Go1 FCloud Server", "create")
        can_write = frappe.has_permission("Go1 FCloud Server", "write")
        can_delete = frappe.has_permission("Go1 FCloud Server", "delete")

        if not can_read:
            return _err("Not permitted to access Go1 FCloud Server.")

        # Build filters
        filters = {}
        if status_filter:
            filters["status"] = status_filter
        if search:
            filters["server_name"] = ("like", f"%{search}%")

        # Status counts (across all servers, before pagination/filters)
        all_servers = frappe.get_list(
            "Go1 FCloud Server",
            fields=["status"],
            ignore_ifnull=True,
        )
        status_counts = {}
        for s in all_servers:
            st = s.get("status") or ""
            status_counts[st] = status_counts.get(st, 0) + 1

        total = len(all_servers)
        active_count = status_counts.get("Active", 0)

        # Filtered + paginated server list
        server_records = frappe.get_list(
            "Go1 FCloud Server",
            filters=filters,
            fields=[
                "name", "server_name", "server_id", "status",
                "region", "price", "vcpu", "memory", "disk",
                "db_server_id", "db_price", "db_vcpu", "db_memory", "db_disk",
                "creation", "modified",
            ],
            order_by="modified desc",
            start=start,
            page_length=limit,
            ignore_ifnull=True,
        )

        # Total count for the current filter set (for pagination)
        total_filtered = frappe.db.count(
            "Go1 FCloud Server", filters=filters
        )
        has_next = (start + limit) < total_filtered

        servers = []
        for s in server_records:
            vcpu = s.get("vcpu") or 0
            memory = s.get("memory") or 0
            disk = s.get("disk") or 0
            db_vcpu = s.get("db_vcpu") or 0
            db_memory = s.get("db_memory") or 0
            db_disk = s.get("db_disk") or 0

            servers.append({
                "name": s.get("name", ""),
                "server_id": s.get("server_id", ""),
                "server_name": s.get("server_name", ""),
                "status": s.get("status", ""),
                "region": s.get("region", ""),
                "creation": s.get("creation", ""),
                "modified": s.get("modified", ""),
                "app_server": {
                    "server_id": s.get("server_id", ""),
                    "vcpu": vcpu,
                    "memory": memory,
                    "disk": disk,
                    "vcpu_display": f"{vcpu} vCPU" if vcpu else "",
                    "memory_display": f"{memory} GB RAM" if memory else "",
                    "disk_display": f"{disk} GB Disk" if disk else "",
                    "price": s.get("price", ""),
                },
                "db_server": {
                    "server_id": s.get("db_server_id", ""),
                    "vcpu": db_vcpu,
                    "memory": db_memory,
                    "disk": db_disk,
                    "vcpu_display": f"{db_vcpu} vCPU" if db_vcpu else "",
                    "memory_display": f"{db_memory} GB RAM" if db_memory else "",
                    "disk_display": f"{db_disk} GB Disk" if db_disk else "",
                    "price": s.get("db_price", ""),
                },
            })

        return _ok({
            "permissions": {
                "can_read": can_read,
                "can_create": can_create,
                "can_write": can_write,
                "can_delete": can_delete,
            },
            "server_count": {
                "total": total,
                "active": active_count,
            },
            "status_list": [
                {"status": "All", "count": total},
                {"status": "Active", "count": active_count},
            ],
            "servers": servers,
            "total_filtered": total_filtered,
            "start": start,
            "limit": limit,
            "has_next": has_next,
        })
    except frappe.PermissionError:
        return _err("Not permitted to access Go1 FCloud Server.")
    except Exception:
        frappe.log_error("mobile_api.get_servers", frappe.get_traceback())
        return _err("Failed to fetch servers.")


def _normalize_memory(raw_memory):
    """Normalize plan memory to GB — API may return MB (e.g. 4096) or GB (e.g. 4)."""
    if raw_memory > 256:
        return round(raw_memory / 1024)
    return raw_memory


def _extract_plan_usage(data):
    """Extract plan and usage from a press.api.client.get Server response."""
    plan = data.get("current_plan") or {}
    usage = data.get("usage") or {}

    vcpu_total = plan.get("vcpu", 0)
    memory_raw = plan.get("memory", 0)
    memory_total = _normalize_memory(memory_raw)
    disk_total = plan.get("disk", 0) or data.get("disk_size", 0)

    cpu_used = max(round(usage.get("vcpu", 0), 1), 0)
    memory_used_mb = usage.get("memory", 0)
    memory_used = round(memory_used_mb / 1024, 1) if memory_used_mb else 0
    disk_used = round(usage.get("disk", 0), 1)

    # Percentage: convert to common unit (MB) for accurate calculation
    memory_total_mb = memory_raw if memory_raw > 256 else memory_raw * 1024
    memory_pct = round((memory_used_mb / memory_total_mb) * 100, 1) if memory_total_mb else 0

    return {
        "plan_name": plan.get("name", ""),
        "plan_title": plan.get("title", ""),
        "platform": plan.get("platform", ""),
        "vcpu": vcpu_total,
        "memory": memory_total,
        "disk": disk_total,
        "price_inr": plan.get("price_inr", ""),
        "price_usd": plan.get("price_usd", ""),
        "usage": {
            "cpu": cpu_used,
            "cpu_total": vcpu_total,
            "cpu_percent": round((cpu_used / vcpu_total) * 100, 1) if vcpu_total else 0,
            "memory": memory_used,
            "memory_total": memory_total,
            "memory_percent": memory_pct,
            "disk": disk_used,
            "disk_total": disk_total,
            "disk_percent": round((disk_used / disk_total) * 100, 1) if disk_total else 0,
        },
    }


def _fetch_server_doc(server_id, doctype="Server"):
    """Fetch a server document from Frappe Cloud via press.api.client.get."""
    return unwrap(cloud_post("press.api.client.get", {
        "doctype": doctype,
        "name": server_id,
    })) or {}


@frappe.whitelist()
def get_server(name):
    """Return full details for a server fetched live from Frappe Cloud."""
    try:
        _require_role()

        # Support both local doc name and direct server ID
        try:
            doc = frappe.get_doc("Go1 FCloud Server", name)
            server_id = doc.server_id or doc.server_name or name
        except Exception:
            server_id = name
            doc = None

        # Single API call gets plan, usage, database_server, actions, etc.
        app_data = _fetch_server_doc(server_id, "Server")
        app_plan_usage = _extract_plan_usage(app_data)

        # Database server plan + usage
        db_server_id = app_data.get("database_server", "")
        db_plan_usage = {}
        if db_server_id:
            try:
                db_data = _fetch_server_doc(db_server_id, "Database Server")
                db_plan_usage = _extract_plan_usage(db_data)
            except Exception:
                pass

        return _ok({
            "name": doc.name if doc else server_id,
            "server_id": server_id,
            "server_name": app_data.get("title", ""),
            "status": app_data.get("status", ""),
            "cluster": app_data.get("cluster", ""),
            "provider": app_data.get("provider", ""),
            "is_unified_server": app_data.get("is_unified_server", 0),
            "creation": app_data.get("creation", ""),
            "owner_email": app_data.get("owner_email", ""),
            "app_server": {
                "name": server_id,
                **app_plan_usage,
            },
            "database_server": {
                "name": db_server_id,
                **db_plan_usage,
            } if db_plan_usage else {"name": db_server_id},
            "actions": app_data.get("actions") or [],
        })
    except Exception:
        frappe.log_error("mobile_api.get_server", frappe.get_traceback())
        return _err(f"Failed to fetch server: {name}")


@frappe.whitelist()
def get_server_overview(name):
    """
    Return server overview: info, plan, current resource usage with
    separate app/database server plans and usage percentages.

    Uses press.api.client.get for complete data in fewer API calls.

    Args:
      name: Go1 FCloud Server doc name or server ID
    """
    try:
        _require_role()

        try:
            doc = frappe.get_doc("Go1 FCloud Server", name)
            server_id = doc.server_id or doc.server_name or name
        except Exception:
            server_id = name
            doc = None

        # Single API call gets plan, usage, database_server, actions, etc.
        app_data = _fetch_server_doc(server_id, "Server")
        app_plan_usage = _extract_plan_usage(app_data)

        # Database server plan + usage
        db_server_id = app_data.get("database_server", "")
        db_plan_usage = {}
        if db_server_id:
            try:
                db_data = _fetch_server_doc(db_server_id, "Database Server")
                db_plan_usage = _extract_plan_usage(db_data)
            except Exception:
                pass

        return _ok({
            "name": doc.name if doc else server_id,
            "server_id": server_id,
            "server_name": app_data.get("title", getattr(doc, "server_name", "")),
            "status": app_data.get("status", getattr(doc, "status", "")),
            "cluster": app_data.get("cluster", ""),
            "provider": app_data.get("provider", ""),
            "is_unified_server": app_data.get("is_unified_server", 0),
            "creation": app_data.get("creation", ""),
            "owner_email": app_data.get("owner_email", ""),
            "app_server": {
                "name": server_id,
                **app_plan_usage,
            },
            "database_server": {
                "name": db_server_id,
                **db_plan_usage,
            } if db_plan_usage else {"name": db_server_id},
            "actions": app_data.get("actions") or [],
        })
    except Exception:
        frappe.log_error("mobile_api.get_server_overview", frappe.get_traceback())
        return _err(f"Failed to fetch server overview: {name}")


@frappe.whitelist()
def get_server_analytics(name, duration="24h", timezone=None):
    """
    Return time-series analytics for a server.

    Args:
      name:     Go1 FCloud Server doc name or server ID
      duration: "1h" | "6h" | "24h" | "7d"  (default "24h")
      timezone: IANA timezone string (default: system timezone)
    """
    _require_role()

    # Resolve server ID
    try:
        doc = frappe.get_doc("Go1 FCloud Server", name)
        server_id = doc.server_id or doc.server_name or name
    except Exception:
        server_id = name

    try:
        tz = timezone or frappe.utils.get_system_timezone()
    except Exception:
        tz = "UTC"

    duration_map = {"1h": 1, "6h": 6, "24h": 24, "7d": 168}
    hours = duration_map.get(duration, 24)
    end = datetime.now()
    start = end - timedelta(hours=hours)
    start_str = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_str = end.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def _fetch_metric(query):
        """Fetch a single analytics metric, return safe defaults on any error."""
        try:
            params = {
                "name": server_id,
                "timezone": tz,
                "start": start_str,
                "end": end_str,
                "query": query,
            }
            result = unwrap(cloud_post("press.api.server.analytics", params))
            if not isinstance(result, dict):
                return {"datasets": [], "labels": [], "avg": 0, "peak": 0}

            datasets = result.get("datasets") or []
            labels = result.get("labels") or []
            first_ds = datasets[0] if datasets else None
            raw_values = (first_ds.get("values") or first_ds.get("data") or []) if isinstance(first_ds, dict) else []
            values = [v for v in raw_values if isinstance(v, (int, float))]
            avg_val = round(sum(values) / len(values), 2) if values else 0
            peak_val = round(max(values), 2) if values else 0

            return {
                "datasets": datasets,
                "labels": labels,
                "avg": avg_val,
                "peak": peak_val,
            }
        except Exception:
            return {"datasets": [], "labels": [], "avg": 0, "peak": 0}

    # API query names → response keys
    metric_queries = {
        "cpu": "loadavg",
        "memory": "memory",
        "network": "network",
        "iops": "iops",
    }

    metrics = {}
    for key, query in metric_queries.items():
        metrics[key] = _fetch_metric(query)

    return _ok(metrics)


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

        try:
            doc = frappe.get_doc("Go1 FCloud Server", name)
            server_id = doc.server_id or doc.server_name or name
        except Exception:
            server_id = name
            doc = None

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
        if doc and action == "archive":
            doc.status = "Deleted"
            doc.save(ignore_permissions=True)
        elif doc and action == "rename" and params.get("title"):
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
    Return options for creating a new server.

    Proxies press.api.server.options and adds display helpers to plans.
    Response mirrors the Press API structure:
      regions, regions_data, app_plans, db_plans, plan_types,
      default_plan_type, storage_plan, snapshot_plan.
    """
    try:
        _require_role()
        data = unwrap(cloud_post("press.api.server.options")) or {}

        # Pass through regions, regions_data, plan_types, default_plan_type
        # exactly as Press returns them.
        regions = data.get("regions", [])
        regions_data = data.get("regions_data", {})
        plan_types = data.get("plan_types", {})
        default_plan_type = data.get("default_plan_type", "")

        # Add display helpers to each plan; skip ₹0 plans.
        # Press already returns plans ordered by price_usd asc via
        # Plan.get_plans(). Each plan has: name, title, description,
        # price_usd, price_inr, vcpu, memory, disk, cluster,
        # instance_type, premium, platform, plan_type,
        # allow_unified_server, machine_unavailable.
        days_in_month = frappe.utils.get_last_day(None).day

        def _enrich_plan(p):
            """Add display fields to a plan dict from Press."""
            price_inr = p.get("price_inr", 0) or 0
            price_usd = p.get("price_usd", 0) or 0
            vcpu = p.get("vcpu", 0) or 0
            memory = p.get("memory", 0) or 0
            disk = p.get("disk", 0) or 0
            platform = p.get("platform", "") or ""
            if not p.get("plan_type"):
                p["plan_type"] = default_plan_type
            p["price_inr"] = price_inr
            p["price_usd"] = price_usd
            p["price_per_day_inr"] = round(price_inr / days_in_month, 2) if price_inr else 0
            p["price_per_day_usd"] = round(price_usd / days_in_month, 2) if price_usd else 0
            p["vcpu_display"] = f"{vcpu} vCPU" if vcpu else ""
            p["memory_display"] = f"{memory} GB" if memory else ""
            p["disk_display"] = f"{disk} GB" if disk else ""
            p["platform_display"] = "ARM" if platform == "arm64" else "x86" if platform else ""
            # Pass through fields needed for filtering by region/provider
            p["cluster"] = p.get("cluster", "")
            p["premium"] = p.get("premium", 0)
            p["instance_type"] = p.get("instance_type", "")
            p["allow_unified_server"] = p.get("allow_unified_server", 0)
            p["machine_unavailable"] = p.get("machine_unavailable", 0)
            return p

        raw_app_plans = data.get("app_plans", [])
        raw_db_plans = data.get("db_plans", [])

        app_plans = [
            _enrich_plan(p) for p in raw_app_plans
            if (p.get("price_inr") or p.get("price_usd"))
        ]
        db_plans = [
            _enrich_plan(p) for p in raw_db_plans
            if (p.get("price_inr") or p.get("price_usd"))
        ]

        # Extract unique providers from multiple sources

        providers = set()

        # 1. From regions list (Press returns Cluster docs with cloud_provider)
        for r in regions:
            if isinstance(r, dict):
                cp = r.get("cloud_provider") or ""
                if cp:
                    providers.add(cp)

        # 2. From regions_data (keyed by title, providers is a dict of provider names)
        if not providers:
            for rd in regions_data.values():
                if isinstance(rd, dict):
                    # providers is a dict: {"AWS EC2": {...}, "OCI": {...}}
                    rd_providers = rd.get("providers") or {}
                    if isinstance(rd_providers, dict):
                        for cp in rd_providers.keys():
                            if cp:
                                providers.add(cp)
                    elif isinstance(rd_providers, list):
                        for cp in rd_providers:
                            if cp:
                                providers.add(cp)

        # 3. From plans' cloud_providers lists
        if not providers:
            for p in app_plans + db_plans:
                for cp in p.get("cloud_providers", []):
                    providers.add(cp)

        # 4. Query Cluster doctype directly as last resort
        if not providers and regions:
            try:
                region_names = [
                    r.get("name") if isinstance(r, dict) else r
                    for r in regions if r
                ]
                if region_names:
                    clusters = unwrap(
                        cloud_post(
                            "press.api.client.get_list",
                            {
                                "doctype": "Cluster",
                                "filters": {"name": ["in", region_names]},
                                "fields": ["name", "cloud_provider"],
                                "limit_page_length": 50,
                            },
                        )
                    ) or []
                    for c in clusters:
                        cp = c.get("cloud_provider") or ""
                        if cp:
                            providers.add(cp)
            except Exception:
                frappe.clear_messages()

        return _ok({
            "regions": regions,
            "regions_data": regions_data,
            "plan_types": plan_types,
            "default_plan_type": default_plan_type,
            "app_plans": app_plans,
            "db_plans": db_plans,
            "storage_plan": data.get("storage_plan"),
            "snapshot_plan": data.get("snapshot_plan"),
            "providers": sorted(providers),
        })
    except Exception:
        frappe.log_error("mobile_api.get_server_options", frappe.get_traceback())
        return _err("Failed to fetch server creation options.")


@frappe.whitelist()
def create_server(**kwargs):
    """
    Create a new server on Frappe Cloud.

    Kwargs:
      title:            Server name
      cluster:          Cluster/region name
      plan:             App server plan (machine type / plan name)
      db_plan:          Database server plan (required for "separate" mode, omit for "unified")
      provider:         Cloud provider (e.g. "AWS EC2", "OCI")
      deployment_mode:  "separate" or "unified" (default: "separate")
      service_type:     Plan type / service tier (e.g. "Standard", "Premium")
    """
    try:
        _require_role()

        title = kwargs.get("title")
        cluster = kwargs.get("cluster")
        plan = kwargs.get("plan")
        db_plan = kwargs.get("db_plan")
        provider = kwargs.get("provider")
        deployment_mode = kwargs.get("deployment_mode")
        service_type = kwargs.get("service_type")

        if not title or not cluster or not plan:
            return _err("title, cluster, and plan are required.")

        server = {
            "title": title,
            "cluster": cluster,
            "app_plan": plan,
            "db_plan": db_plan or plan,
        }

        if provider:
            server["provider"] = provider

        if deployment_mode:
            server["deployment_mode"] = deployment_mode

        if service_type:
            server["plan_type"] = service_type

        result = cloud_post("press.api.server.new", {"server": server})
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
def get_marketplace_app_list(bench_name=None, search=None, page=1, page_size=20):
    """
    List published Marketplace Apps available on Frappe Cloud.

    Uses press.api.bench.all_apps which returns apps with image,
    description, sources, repo, and total_installs.

    Args:
      bench_name:  Optional Go1 FCloud Bench doc name to scope apps
                   available for that bench.
      search:      Optional search string to filter by app name, title,
                   or description.
      page:        Page number (default 1)
      page_size:   Number of apps per page (default 20)
    """
    try:
        _require_role()
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))

        if bench_name:
            doc, bench_id = _resolve_bench(bench_name)
        else:
            bench_id = None

        params = {}
        if bench_id:
            params["name"] = bench_id

        apps = unwrap(cloud_post("press.api.bench.all_apps", params)) or []

        # Search filter
        if search:
            q = search.lower()
            apps = [
                a for a in apps
                if q in (a.get("title") or "").lower()
                or q in (a.get("name") or "").lower()
                or q in (a.get("app") or "").lower()
                or q in (a.get("description") or "").lower()
            ]

        total = len(apps)
        start = (page - 1) * page_size
        end = start + page_size
        paginated = apps[start:end]

        return _ok({
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
            "apps": paginated,
        })
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error(
            "mobile_api.get_marketplace_app_list", frappe.get_traceback()
        )
        return _err("Failed to fetch marketplace app list.")


@frappe.whitelist()
def add_app_to_bench(bench_name, apps):
    """
    Add one or multiple marketplace apps to a bench (Release Group).

    Args:
      bench_name:  Go1 FCloud Bench doc name, Cloud bench ID, or title
      apps:        JSON list of app objects, each with "app" and "source"
                   e.g. [{"app": "erpnext", "source": "SRC-erpnext-542"},
                         {"app": "hrms", "source": "SRC-hrms-123"}]
                   Or a single app object: {"app": "erpnext", "source": "SRC-erpnext-542"}
    """
    try:
        _require_role()
        doc, bench_id = _resolve_bench(bench_name)

        app_list = json.loads(apps) if isinstance(apps, str) else apps
        # Support single object as well as list
        if isinstance(app_list, dict):
            app_list = [app_list]

        if not app_list:
            return _err("At least one app is required.")

        results = []
        errors = []
        for item in app_list:
            app_name = item.get("app", "")
            source = item.get("source", "")
            if not app_name or not source:
                errors.append({"app": app_name, "error": "app and source are required."})
                continue
            try:
                result = cloud_post(
                    "press.api.bench.add_app",
                    {"name": bench_id, "source": source, "app": app_name},
                )
                results.append({"app": app_name, "success": True, "data": unwrap(result)})
            except Exception as e:
                errors.append({"app": app_name, "error": str(e)})

        return _ok({"added": results, "errors": errors})
    except frappe.ValidationError as e:
        return _err(str(e))
    except Exception:
        frappe.log_error("mobile_api.add_app_to_bench", frappe.get_traceback())
        return _err("Failed to add apps to bench.")


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
#  GITHUB AUTHENTICATION (connect / disconnect GitHub account)
# =========================================================================== #


@frappe.whitelist()
def get_github_auth_url():
    """
    Return the GitHub App authorization URL so the user can install / authorize
    the Frappe Cloud GitHub App on their GitHub account.

    Endpoint: press.api.github.authorize_url  (GET)

    Response:
      { "success": true, "data": { "url": "https://github.com/apps/..." } }
    """
    try:
        _require_role()
        result = unwrap(cloud_get("press.api.github.authorize_url"))
        return _ok(result)
    except frappe.ValidationError as e:
        frappe.clear_messages()
        return _err(str(e))
    except Exception:
        frappe.clear_messages()
        frappe.log_error("mobile_api.get_github_auth_url", frappe.get_traceback())
        return _err("Failed to fetch GitHub authorization URL.")


@frappe.whitelist()
def get_github_auth_status():
    """
    Check whether GitHub is connected to the Frappe Cloud team.

    Calls press.api.github.options and returns a simplified status indicating
    whether any GitHub App installations are linked.

    Response:
      {
        "success": true,
        "data": {
          "connected": true,
          "installations": [ { "id": ..., "login": ..., ... }, ... ]
        }
      }
    """
    try:
        _require_role()
        result = unwrap(cloud_get("press.api.github.options"))

        # Normalize response — may be a list or dict with installations key
        if isinstance(result, list):
            installations = result
        elif isinstance(result, dict):
            installations = (
                result.get("installations")
                or result.get("options")
                or next((v for v in result.values() if isinstance(v, list)), [])
            )
        else:
            installations = []

        return _ok({
            "connected": len(installations) > 0,
            "installation_count": len(installations),
            "installations": [
                {
                    "id": inst.get("id", ""),
                    "login": inst.get("login", ""),
                    "image": inst.get("image", ""),
                }
                for inst in installations
                if isinstance(inst, dict)
            ],
        })
    except frappe.ValidationError as e:
        frappe.clear_messages()
        error_msg = str(e)
        if "Bad credentials" in error_msg:
            return _ok({
                "connected": False,
                "installation_count": 0,
                "installations": [],
                "error": "GitHub credentials expired. Please re-authorize.",
            })
        return _err(error_msg)
    except Exception:
        frappe.clear_messages()
        frappe.log_error("mobile_api.get_github_auth_status", frappe.get_traceback())
        return _err("Failed to check GitHub connection status.")


@frappe.whitelist()
def clear_github_auth():
    """
    Clear the stored GitHub token and return a fresh GitHub App installation
    URL so the user can re-authorize.

    Endpoint: press.api.github.clear_token_and_get_github_app_url  (POST)

    Response:
      { "success": true, "data": { "url": "https://github.com/apps/..." } }
    """
    try:
        _require_role()
        result = unwrap(
            cloud_post("press.api.github.clear_token_and_get_github_app_url")
        )
        return _ok(result)
    except frappe.ValidationError as e:
        frappe.clear_messages()
        return _err(str(e))
    except Exception:
        frappe.clear_messages()
        frappe.log_error("mobile_api.clear_github_auth", frappe.get_traceback())
        return _err("Failed to clear GitHub authorization.")


# =========================================================================== #
#  GITHUB APP MANAGEMENT (Add custom apps from GitHub — public & private)
# =========================================================================== #


@frappe.whitelist()
def get_github_installations():
    """
    Return GitHub App installations (organizations / users) linked to the
    Frappe Cloud team.

    Endpoint: press.api.github.options

    Response shape:
      { "success": true, "data": [ { "id": ..., "login": ..., ... }, ... ] }
    """
    try:
        _require_role()
        result = unwrap(cloud_get("press.api.github.options"))
        return _ok(result)
    except frappe.ValidationError as e:
        frappe.clear_messages()
        error_msg = str(e)
        if "Bad credentials" in error_msg:
            return _err(
                "GitHub App credentials are invalid or expired. "
                "Please reconnect your GitHub account on Frappe Cloud "
                "(Settings → GitHub App Integration)."
            )
        return _err(error_msg)
    except Exception:
        frappe.clear_messages()
        frappe.log_error("mobile_api.get_github_installations", frappe.get_traceback())
        return _err("Failed to fetch GitHub installations.")


@frappe.whitelist()
def get_github_repositories(installation, owner, search=None):
    """
    Return repositories accessible via a GitHub App installation.

    Extracts repos from the press.api.github.options response by matching
    the given installation ID or owner login.

    Args:
      installation:  GitHub App installation ID (from get_github_installations)
      owner:         GitHub org / user login (e.g. "pra17shant")
      search:        Optional search string to filter repos by name

    Returns:
      { "success": true, "data": [ { "id": ..., "name": ..., "private": ..., ... }, ... ] }
    """
    try:
        _require_role()
        result = unwrap(cloud_get("press.api.github.options")) or []

        # Normalize: result may be a flat list [...] or a dict {"installations": [...]}
        if isinstance(result, list):
            installations = result
        elif isinstance(result, dict):
            installations = (
                result.get("installations")
                or result.get("options")
                or next((v for v in result.values() if isinstance(v, list)), [])
            )
        else:
            installations = []

        install_str = str(installation) if installation else ""
        repos = []

        for inst in installations:
            if not isinstance(inst, dict):
                continue
            if str(inst.get("id", "")) == install_str or inst.get("login", "") == owner:
                repos = inst.get("repos", [])
                break

        # Filter by search query
        if search and repos:
            q = search.lower()
            repos = [r for r in repos if q in (r.get("name") or "").lower()]

        return _ok(repos)
    except frappe.ValidationError as e:
        frappe.clear_messages()
        error_msg = str(e)
        if "Bad credentials" in error_msg:
            return _err(
                "GitHub App credentials are invalid or expired. "
                "Please reconnect your GitHub account on Frappe Cloud."
            )
        return _err(error_msg)
    except Exception as e:
        frappe.clear_messages()
        frappe.log_error("mobile_api.get_github_repositories", frappe.get_traceback())
        return _err(f"Failed to fetch GitHub repositories: {str(e)}")


@frappe.whitelist()
def get_github_branches(installation, owner, repo):
    """
    Return branches for a private GitHub repository.

    Args:
      installation:  GitHub App installation ID
      owner:         GitHub org / user login
      repo:          Repository name (e.g. "ParasonCustomapp")

    Endpoint: press.api.github.repository
    (param "name" = repo name, returns repo details including branches)
    """
    try:
        _require_role()
        # Cast to int — Frappe sends POST params as strings but Press
        # needs an integer to look up the GitHub App installation token.
        install_id = int(installation) if installation else None
        result = unwrap(
            cloud_post(
                "press.api.github.repository",
                {"installation": install_id, "owner": owner, "name": repo},
            )
        )
        return _ok(result)
    except frappe.ValidationError as e:
        frappe.clear_messages()
        error_msg = str(e)
        if "Bad credentials" in error_msg:
            return _err(
                "GitHub App credentials are invalid or expired. "
                "Please reconnect your GitHub account on Frappe Cloud."
            )
        return _err(error_msg)
    except Exception as e:
        frappe.clear_messages()
        frappe.log_error("mobile_api.get_github_branches", frappe.get_traceback())
        return _err(f"Failed to fetch branches: {str(e)}")


@frappe.whitelist()
def validate_github_app(installation, owner, repo, branch):
    """
    Validate that a GitHub repository + branch contains a valid Frappe app.

    Returns the detected app title and name (e.g. "Found Sapcon (sapcon)").

    Args:
      installation:  GitHub App installation ID
      owner:         GitHub org / user login
      repo:          Repository name
      branch:        Git branch name

    Endpoint: press.api.github.app
    """
    try:
        _require_role()
        install_id = int(installation) if installation else None
        result = unwrap(
            cloud_post(
                "press.api.github.app",
                {
                    "installation": install_id,
                    "owner": owner,
                    "repository": repo,
                    "branch": branch,
                },
            )
        )
        return _ok(result)
    except frappe.ValidationError as e:
        frappe.clear_messages()
        error_msg = str(e)
        if "Bad credentials" in error_msg:
            return _err(
                "GitHub App credentials are invalid or expired. "
                "Please reconnect your GitHub account on Frappe Cloud."
            )
        return _err(error_msg)
    except Exception:
        frappe.clear_messages()
        frappe.log_error("mobile_api.validate_github_app", frappe.get_traceback())
        return _err("Failed to validate app.")


@frappe.whitelist()
def fetch_public_repo_branches(url):
    """
    Fetch branches for a public GitHub repository given its URL.

    Args:
      url:  Public GitHub repository URL
            (e.g. "https://github.com/ArkOne-Softwares/frappe_sapcon")

    Parses the URL to extract owner/repo, then queries the GitHub REST API
    (no authentication required for public repositories).
    """
    import re
    import requests as _requests

    try:
        _require_role()

        # Parse owner and repo from URL
        match = re.match(
            r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", (url or "").strip()
        )
        if not match:
            return _err(
                "Invalid GitHub URL. Expected format: https://github.com/owner/repo"
            )

        owner, repo = match.group(1), match.group(2)

        # Fetch branches from GitHub public API
        gh_url = f"https://api.github.com/repos/{owner}/{repo}/branches"
        resp = _requests.get(gh_url, timeout=15, params={"per_page": 100})
        if resp.status_code == 404:
            return _err(f"Repository '{owner}/{repo}' not found or is private.")
        resp.raise_for_status()

        branches = [{"name": b["name"]} for b in resp.json()]
        return _ok({"owner": owner, "repo": repo, "branches": branches})
    except frappe.ValidationError as e:
        return _err(str(e))
    except _requests.exceptions.RequestException as e:
        frappe.log_error("mobile_api.fetch_public_repo_branches", str(e))
        return _err("Failed to fetch branches from GitHub.")
    except Exception:
        frappe.log_error(
            "mobile_api.fetch_public_repo_branches", frappe.get_traceback()
        )
        return _err("Failed to fetch branches.")


@frappe.whitelist()
def add_github_app_to_bench(
    bench_name, title, url, branch, github_installation_id=None
):
    """
    Add a custom GitHub app to a bench (Release Group).

    Works for both public and private repositories.

    Args:
      bench_name:              Go1 FCloud Bench doc name, Cloud bench ID, or title
      title:                   App display title (e.g. "Sapcon")
      url:                     GitHub repository URL
      branch:                  Git branch name
      github_installation_id:  GitHub App installation ID (required for private repos,
                               omit for public repos)

    Endpoint: press.api.app.new
    """
    try:
        _require_role()
        doc, bench_id = _resolve_bench(bench_name)

        if not title or not url or not branch:
            return _err("title, url, and branch are required.")

        payload = {
            "app": {
                "title": title,
                "name": title.lower().replace(" ", "_"),
                "repository_url": url,
                "branch": branch,
                "group": bench_id,
                "github_installation_id": int(github_installation_id) if github_installation_id else "",
            }
        }
        result = cloud_post("press.api.app.new", payload)
        return _ok(unwrap(result))
    except frappe.ValidationError as e:
        frappe.clear_messages()
        return _err(str(e))
    except Exception:
        frappe.clear_messages()
        frappe.log_error("mobile_api.add_github_app_to_bench", frappe.get_traceback())
        return _err("Failed to add app to bench.")


# =========================================================================== #
#  SYNC  (pull Frappe Cloud data into local Frappe DocTypes)
# =========================================================================== #


@frappe.whitelist()
def sync_all():
    """
    Enqueue sync of sites, benches, and servers from Frappe Cloud.
    Returns immediately; sync runs in the background.
    Syncs run sequentially: servers → benches → sites (dependency order).
    """
    try:
        _require_role()
        frappe.enqueue(
            _sync_all_sequential, queue="long", job_name="fc_sync_all"
        )
        return _ok({"message": "Sync started in background. Refresh after a minute."})
    except Exception:
        frappe.log_error("mobile_api.sync_all", frappe.get_traceback())
        return _err("Failed to start sync.")


def _sync_all_sequential():
    """Run all three syncs in dependency order: servers → benches → sites."""
    from go1_fcloud.go1_fcloud.doctype.go1_fcloud_server.go1_fcloud_server import (
        sync_server,
    )
    from go1_fcloud.go1_fcloud.doctype.go1_fcloud_bench.go1_fcloud_bench import (
        sync_bench,
    )
    from go1_fcloud.go1_fcloud.doctype.go1_fcloud_site.go1_fcloud_site import (
        sync_site,
    )

    sync_server()
    sync_bench()
    sync_site()


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


@frappe.whitelist()
def sync_servers_only():
    """Enqueue server sync only."""
    try:
        _require_role()
        from go1_fcloud.go1_fcloud.doctype.go1_fcloud_server.go1_fcloud_server import (
            sync_server,
        )

        frappe.enqueue(sync_server, queue="long", job_name="fc_sync_server")
        return _ok({"message": "Server sync started."})
    except Exception:
        frappe.log_error("mobile_api.sync_servers_only", frappe.get_traceback())
        return _err("Failed to start server sync.")


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


# =========================================================================== #
#  DOCTYPE PERMISSIONS
# =========================================================================== #


@frappe.whitelist()
def get_doctype_permissions(doctypes=None):
    """
    Return the current user's permissions for the requested doctypes.

    Only users linked to an active Employee record can access this endpoint.

    Args:
      doctypes: JSON list of doctype names, or a single doctype name string.
                Defaults to DEFAULT_PERMISSION_DOCTYPES if omitted.

    Returns:
      {
        "status": "Success",
        "data": {
          "Go1 FCloud Site": {
            "read": true, "write": true, "create": false, "delete": false,
            "submit": false, "amend": false, "is_submittable": false,
            "istable": false, "if_owner": { ... }
          },
          ...
        }
      }
    """
    import frappe.permissions

    try:
        user = frappe.session.user
        if not user or user == "Guest":
            return {"status": "Failed", "message": "Not logged in"}

        # Employee role validation — user must be linked to an active Employee
        employee = frappe.db.get_value(
            "Employee",
            {"user_id": user, "status": "Active"},
            "name",
        )
        if not employee:
            return {"status": "Failed", "message": "No active Employee record linked to this user."}

        if isinstance(doctypes, str):
            doctypes = frappe.parse_json(doctypes)
        if not doctypes:
            doctypes = DEFAULT_PERMISSION_DOCTYPES
        if isinstance(doctypes, str) or not isinstance(doctypes, (list, tuple)):
            doctypes = [doctypes]

        requested = []
        for dt in doctypes:
            if not isinstance(dt, str):
                continue
            dt = dt.strip()
            if dt and dt not in requested:
                requested.append(dt)

        rights = frappe.permissions.rights

        # Clear permission cache so recent Role Permission Manager changes
        # are reflected immediately instead of returning stale cached values.
        frappe.clear_cache(user=user)

        data = {}
        for dt in requested:
            try:
                if not frappe.db.exists("DocType", dt):
                    continue
                meta = frappe.get_meta(dt, cached=False)
                is_submittable = bool(meta.is_submittable)

                # Use has_permission per right for accurate, cache-free results
                result = {}
                for right in rights:
                    try:
                        result[right] = frappe.has_permission(dt, right, user=user)
                    except (frappe.PermissionError, Exception):
                        result[right] = False

                if not is_submittable:
                    result["submit"] = False
                    result["amend"] = False
                    result["cancel"] = False
                result["is_submittable"] = is_submittable
                result["istable"] = bool(meta.istable)

                # if_owner permissions
                perms = frappe.permissions.get_role_permissions(meta, user=user)
                if perms.get("has_if_owner_enabled"):
                    owner_perms = frappe.permissions.get_role_permissions(
                        meta, user=user, is_owner=True
                    )
                    owner_rights = owner_perms.get("if_owner") or {}
                    if_owner = {right: bool(owner_rights.get(right)) for right in rights}
                    if not is_submittable:
                        if_owner["submit"] = False
                        if_owner["amend"] = False
                        if_owner["cancel"] = False
                    result["if_owner"] = if_owner
                else:
                    result["if_owner"] = {}

                data[dt] = result
            except Exception:
                frappe.log_error(
                    title="get_doctype_permissions",
                    message=frappe.get_traceback(),
                )

        return {"status": "Success", "data": data}
    except Exception as e:
        frappe.log_error(
            title="get_doctype_permissions", message=frappe.get_traceback()
        )
        return {"status": "Failed", "message": str(e)}
