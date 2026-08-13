# Copyright (c) 2024, Tridots Tech and contributors
# For license information, please see license.txt
#
# go1_fcloud_site.py — Site DocType controller.
#
# API changes vs. original go1_fcloud:
#   - press.api.site.exists       → press.api.site.domain_exists
#   - press.api.site.jobs         → press.api.site.running_jobs (for active jobs)
#                                 + press.api.site.activities  (for history)
#   - press.api.site.job          → press.api.site.job  (unchanged, takes job name)
#   - get_token / make_request    → removed; use go1_fcloud.utils helpers
#   - URL base                    → always frappecloud.com (no more cloud.frappe.io mix)

import frappe
import json
from frappe.model.document import Document
from go1_fcloud.utils import cloud_get, cloud_post, unwrap


class Go1FCloudSite(Document):

    def validate(self):
        if not self.group:
            self.group = (
                frappe.db.get_value("Go1 FCloud Bench", self.bench_name, "id")
                if self.bench_name
                else None
            )

    # ------------------------------------------------------------------ #
    #  Site Creation / Options
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def get_options_for_site(self):
        """
        Return group/cluster/plan options for creating a new site.
        Endpoint: press.api.site.options_for_new
        """
        try:
            return unwrap(cloud_get("press.api.site.options_for_new"))
        except Exception:
            frappe.log_error("get_options_for_site", frappe.get_traceback())

    @frappe.whitelist()
    def get_new_site_options(self, args=None):
        """
        Return shared-bench site options (groups, clusters, plans).
        Endpoint: press.api.site.get_new_site_options
        """
        try:
            return unwrap(cloud_post("press.api.site.get_new_site_options"))
        except Exception:
            frappe.log_error("get_new_site_options", frappe.get_traceback())

    @frappe.whitelist()
    def get_site_plans(self, args=None):
        """
        Return available site plans.
        Endpoint: press.api.site.get_site_plans
        """
        try:
            return unwrap(cloud_get("press.api.site.get_site_plans"))
        except Exception:
            frappe.log_error("get_site_plans", frappe.get_traceback())

    @frappe.whitelist()
    def site_exists(self):
        """
        Check whether a subdomain is already taken.
        CHANGE: press.api.site.exists → press.api.site.domain_exists(domain)
        """
        try:
            if not self.url:
                domain = f"{self.site_name}.frappe.cloud"
                response = cloud_post(
                    "press.api.site.domain_exists", {"domain": domain}
                )
                return response
        except Exception:
            frappe.log_error("site_exists", frappe.get_traceback())

    # ------------------------------------------------------------------ #
    #  CRUD / Lifecycle
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def create_site(self, args):
        """
        Create a new Frappe Cloud site.
        Endpoint: press.api.site.new
        """
        try:
            # breakpoint()
            # Verify bench is active before attempting creation
            if args.group:
                bench = unwrap(cloud_post("press.api.bench.get", {"name": args.group}))
                if not bench:
                    frappe.throw("Bench not found on Frappe Cloud.")
                if bench.get("status") != "Active":
                    frappe.throw(
                        "Bench is not Active. Check Deploys or deploy the bench first "
                        "before creating a site."
                    )

            apps = ["frappe"]
            if args.apps:
                for app in args.apps:
                    title = app.get("title") if isinstance(app, dict) else app["title"]
                    if title not in apps:
                        apps.append(title)

            site_payload = {
                "name": args.name,
                "apps": apps,
                "group": args.group,
                "cluster": args.cluster,
                "plan": args.plan,
            }
            # Private bench: add subdomain hint
            if getattr(args, "bench", None):
                site_payload["Subdomain"] = args.name

            response = cloud_post("press.api.site.new", {"site": site_payload})
            return response
        except frappe.ValidationError:
            raise
        except Exception:
            frappe.log_error("create_site", frappe.get_traceback())

    @frappe.whitelist()
    def drop_site(self):
        """
        Archive (delete) a site on Frappe Cloud.
        Endpoint: press.api.site.archive
        """
        try:
            response = cloud_post(
                "press.api.site.archive",
                {"name": self.url, "force": True},
            )
            if response is not None:
                doc = frappe.get_doc("Go1 FCloud Site", self.name)
                doc.is_dropped = 1
                doc.status = "Archived"
                doc.save(ignore_permissions=True)
            return response
        except Exception:
            frappe.log_error("drop_site", frappe.get_traceback())

    @frappe.whitelist()
    def activate_site(self):
        """Endpoint: press.api.site.activate"""
        try:
            return cloud_post("press.api.site.activate", {"name": self.url})
        except Exception:
            frappe.log_error("activate_site", frappe.get_traceback())

    @frappe.whitelist()
    def deactivate_site(self):
        """Endpoint: press.api.site.deactivate"""
        try:
            return cloud_post("press.api.site.deactivate", {"name": self.url})
        except Exception:
            frappe.log_error("deactivate_site", frappe.get_traceback())

    @frappe.whitelist()
    def admin_login(self):
        """
        Get a one-time login URL for the site admin.
        Endpoint: press.api.site.login
        """
        try:
            return cloud_post("press.api.site.login", {"name": self.url})
        except Exception:
            frappe.log_error("admin_login", frappe.get_traceback())

    # ------------------------------------------------------------------ #
    #  Backup / Restore
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def schedule_backup(self):
        """
        Schedule an on-demand backup (with files).
        Endpoint: press.api.site.backup
        """
        try:
            return cloud_post(
                "press.api.site.backup",
                {"name": self.url, "with_files": True},
            )
        except Exception:
            frappe.log_error("schedule_backup", frappe.get_traceback())

    @frappe.whitelist()
    def backup_site(self):
        """
        List all backups for the site.
        Endpoint: press.api.site.backups
        """
        try:
            response = cloud_post("press.api.site.backups", {"name": self.url})
            return response
        except Exception:
            frappe.log_error("backup_site", frappe.get_traceback())

    @frappe.whitelist()
    def restore_site(self, args):
        """
        Restore a site from another site's backup.
        Fetches remote backup links, then calls press.api.site.restore.
        """
        try:
            remote_files = unwrap(
                cloud_post(
                    "press.api.site.get_backup_links",
                    {
                        "url": args.from_site_url,
                        "email": args.from_site_username,
                        "password": args.password,
                    },
                )
            )

            files = {"database": "", "public": "", "private": ""}
            for item in remote_files or []:
                t = item.get("type")
                if t == "database":
                    files["database"] = item.get("remote_file", "")
                elif t == "public":
                    files["public"] = item.get("remote_file", "")
                elif t == "private":
                    files["private"] = item.get("remote_file", "")

            return cloud_post(
                "press.api.site.restore",
                {"name": args.restore_site_url, "files": files},
            )
        except Exception:
            frappe.log_error("restore_site", frappe.get_traceback())

    # ------------------------------------------------------------------ #
    #  App Management
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def get_site_apps(self, args):
        """
        List apps installed on a specific site.
        Endpoint: press.api.site.installed_apps
        """
        try:
            return unwrap(
                cloud_post("press.api.site.installed_apps", {"name": args.title})
            )
        except Exception:
            frappe.log_error("get_site_apps", frappe.get_traceback())

    @frappe.whitelist()
    def available_custom_apps(self, args):
        """
        List apps available to install on the site (from its bench).
        Endpoint: press.api.site.available_apps
        """
        try:
            return unwrap(
                cloud_post("press.api.site.available_apps", {"name": args.url})
            )
        except Exception:
            frappe.log_error("available_custom_apps", frappe.get_traceback())

    @frappe.whitelist()
    def install_app_on_site(self, args):
        """
        Install an app on the site.
        Endpoint: press.api.site.install_app
        """
        try:
            return cloud_post(
                "press.api.site.install_app",
                {"name": args.title, "app": args.app},
            )
        except Exception:
            frappe.log_error("install_app_on_site", frappe.get_traceback())

    @frappe.whitelist()
    def remove_app(self, args):
        """
        Uninstall an app from the site.
        Endpoint: press.api.site.uninstall_app
        """
        try:
            return cloud_post(
                "press.api.site.uninstall_app",
                {"name": args.name, "app": args.app},
            )
        except Exception:
            frappe.log_error("remove_app", frappe.get_traceback())

    # ------------------------------------------------------------------ #
    #  Migrations / Updates
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def migrate(self, args):
        """
        Run database migrations on the site.
        Endpoint: press.api.site.migrate
        """
        try:
            return cloud_post("press.api.site.migrate", {"name": args.id})
        except Exception:
            frappe.log_error("migrate", frappe.get_traceback())

    @frappe.whitelist()
    def clear_site_cache(self, site_name=None):
        """
        Clear the site's cache.
        Endpoint: press.api.site.clear_cache
        """
        try:
            name = site_name or self.url
            return cloud_post("press.api.site.clear_cache", {"name": name})
        except Exception:
            frappe.log_error("clear_site_cache", frappe.get_traceback())

    @frappe.whitelist()
    def setup_wizard_complete(self):
        """
        Mark the site's setup wizard as complete.
        Endpoint: press.api.site.setup_wizard_complete
        """
        try:
            return cloud_post(
                "press.api.site.setup_wizard_complete", {"name": self.url}
            )
        except Exception:
            frappe.log_error("setup_wizard_complete", frappe.get_traceback())

    # ------------------------------------------------------------------ #
    #  Job / Activity Tracking
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def get_running_jobs(self, args):
        """
        Return jobs currently running on the site.
        CHANGE: press.api.site.jobs (old) → press.api.site.running_jobs (new)
        """
        try:
            return unwrap(
                cloud_post("press.api.site.running_jobs", {"name": args.title})
            )
        except Exception:
            frappe.log_error("get_running_jobs", frappe.get_traceback())

    @frappe.whitelist()
    def get_site_activities(self, args):
        """
        Return site activity log (history of all jobs).
        Endpoint: press.api.site.activities  (NEW — replaces old jobs list)
        """
        try:
            return unwrap(
                cloud_post(
                    "press.api.site.activities",
                    {
                        "filters": {"site": args.title},
                        "order_by": "creation desc",
                        "limit_start": 0,
                        "limit_page_length": getattr(args, "limit", 20),
                    },
                )
            )
        except Exception:
            frappe.log_error("get_site_activities", frappe.get_traceback())

    @frappe.whitelist()
    def get_job_status(self, job_name):
        """
        Poll a single job's status.
        Endpoint: press.api.site.get_job_status  (NEW — replaces press.api.site.job)
        """
        try:
            return unwrap(
                cloud_post("press.api.site.get_job_status", {"job_name": job_name})
            )
        except Exception:
            frappe.log_error("get_job_status", frappe.get_traceback())

    # ------------------------------------------------------------------ #
    #  Status Sync (refresh local doc from cloud)
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def get_status(self, args):
        """
        Refresh the local Go1 FCloud Site document from Frappe Cloud data.
        Updates: status, bench_status, installed apps, running jobs.
        """
        try:
            update_doc = frappe.get_doc("Go1 FCloud Site", args.doc)

            # --- Site status ---
            site_data = unwrap(cloud_post("press.api.site.get", {"name": args.title}))
            if not site_data:
                # Try archived variant
                site_data = unwrap(
                    cloud_post("press.api.site.get", {"name": f"{args.title}.archived"})
                )
            if site_data:
                update_doc.status = site_data.get("status", "")

            # --- Bench status ---
            if args.group:
                bench = unwrap(cloud_post("press.api.bench.get", {"name": args.group}))
                if bench:
                    update_doc.bench_status = bench.get("status", "")

            # --- Installed apps on site ---
            apps = (
                unwrap(
                    cloud_post("press.api.site.installed_apps", {"name": args.title})
                )
                or []
            )
            update_doc.custom = []
            for app in apps:
                update_doc.append(
                    "custom",
                    {
                        "title": app.get("app", ""),
                        "app_name": app.get("repository", ""),
                    },
                )

            # --- Apps on bench ---
            if getattr(args, "bench", None):
                bench_apps = (
                    unwrap(cloud_post("press.api.bench.apps", {"name": args.group}))
                    or []
                )
                update_doc.installed = []
                for app in bench_apps:
                    update_doc.append("installed", {"app_name": app.get("name", "")})

            # --- Running jobs (CHANGE: running_jobs replaces jobs list) ---
            running = (
                unwrap(cloud_post("press.api.site.running_jobs", {"name": args.title}))
                or []
            )

            # Also fetch recent activities for history
            activities = (
                unwrap(
                    cloud_post(
                        "press.api.site.activities",
                        {
                            "filters": {"site": args.title},
                            "order_by": "creation desc",
                            "limit_page_length": 10,
                        },
                    )
                )
                or []
            )

            update_doc.jobs = []
            all_jobs = running + [a for a in activities if a not in running]
            for job in all_jobs[:10]:
                fmt_time, duration = "", ""
                if job.get("creation") and job.get("duration"):
                    fmt_time, duration = _format_duration(
                        job["creation"], job["duration"]
                    )
                update_doc.append(
                    "jobs",
                    {
                        "title": job.get("job_type", job.get("type", "")),
                        "creation": job.get("creation", ""),
                        "status": job.get("status", ""),
                        "steps": json.dumps(job.get("steps", []), indent=2),
                        "completed": fmt_time or None,
                        "duration": duration or None,
                    },
                )

            update_doc.save(ignore_permissions=True)
            return "Completed"

        except Exception:
            frappe.log_error("get_status", frappe.get_traceback())

    # ------------------------------------------------------------------ #
    #  Bench helpers (called from Site context)
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def get_bench_list(self):
        """Endpoint: press.api.bench.all"""
        try:
            return unwrap(cloud_post("press.api.bench.all"))

        except Exception:
            frappe.log_error("get_bench_list", frappe.get_traceback())

    @frappe.whitelist()
    def get_bench_name(self, args):
        """Endpoint: press.api.bench.get"""
        try:
            return cloud_post("press.api.bench.get", {"name": args.title})
        except Exception:
            frappe.log_error("get_bench_name", frappe.get_traceback())

    @frappe.whitelist()
    def get_go1_bench(self, args):
        """Look up local Go1 FCloud Bench doc by cloud bench ID."""
        try:
            doc = frappe.get_doc("Go1 FCloud Bench", {"bench": args.doc})
            return doc.name
        except Exception:
            frappe.log_error("get_go1_bench", frappe.get_traceback())

    # ------------------------------------------------------------------ #
    #  Misc
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def get_permission(self):
        """Get current Frappe Cloud account info."""
        try:
            return unwrap(cloud_post("press.api.account.get"))
        except Exception:
            frappe.log_error("get_permission", frappe.get_traceback())

    @frappe.whitelist()
    def get_all_site(self):
        """List all cloud sites."""
        try:
            return unwrap(cloud_post("press.api.site.all"))
        except Exception:
            frappe.log_error("get_all_site", frappe.get_traceback())

    @frappe.whitelist()
    def get_apps(self, args):
        """List all apps on Frappe Cloud (for dropdowns)."""
        try:
            return unwrap(cloud_post("press.api.bench.apps", {"name": args.name}))
        except Exception:
            frappe.log_error("get_apps", frappe.get_traceback())

    @frappe.whitelist()
    def get_installed_apps(self, args):
        """List apps installed on a bench (Release Group)."""
        try:
            return unwrap(cloud_post("press.api.bench.apps", {"name": args.title}))
        except Exception:
            frappe.log_error("get_installed_apps", frappe.get_traceback())


# --------------------------------------------------------------------------- #
#  Module-level sync functions (called via frappe.enqueue)
# --------------------------------------------------------------------------- #


@frappe.whitelist()
def sync_site_enqueue():
    """Enqueue a long-running site sync from Frappe Cloud."""
    try:
        frappe.enqueue(sync_site, queue="long")
    except Exception:
        frappe.log_error("sync_site_enqueue", frappe.get_traceback())


def sync_site():
    """
    Pull all sites from Frappe Cloud and create/update local docs.
    Called by sync_site_enqueue.
    """
    from go1_fcloud.utils import cloud_post, cloud_get, unwrap

    try:
        cloud_sites = unwrap(cloud_post("press.api.site.all")) or []
        site_plans = unwrap(cloud_get("press.api.site.get_site_plans")) or []
        shared_options = unwrap(cloud_post("press.api.site.get_new_site_options")) or []
        bench_list = unwrap(cloud_post("press.api.bench.all")) or []

        local_sites = frappe.get_all(
            "Go1 FCloud Site", filters={"is_dropped": 0}, fields=["url", "name"]
        )
        local_urls = {s["url"] for s in local_sites}

        for site in cloud_sites:
            site_name = site.get("name", "")
            if site_name in local_urls:
                continue  # Already synced

            doc = frappe.new_doc("Go1 FCloud Site")
            parts = site_name.partition(".")
            doc.site_name = parts[0]
            doc.status = site.get("status", "")
            doc.region = site.get("cluster", "")
            doc.version = site.get("version", "")
            doc.url = site_name
            doc.group = site.get("group", "")
            doc.plans = json.dumps(site_plans)
            doc.bench_data = json.dumps(bench_list)
            doc.site_data = json.dumps(shared_options)

            plan = site.get("plan")
            if plan:
                doc.plan = (
                    f"{plan.get('name','')} - INR {int(plan.get('price_inr', 0))}"
                )

            # Private bench site
            title = site.get("title", "")
            version = site.get("version", "")
            if title and title != version:
                bench_doc_name = frappe.db.get_value(
                    "Go1 FCloud Bench", {"bench": title}, "name"
                )
                if bench_doc_name:
                    doc.bench_name = bench_doc_name
                doc.bench = title

                # Apps
                bench_apps = (
                    unwrap(
                        cloud_post(
                            "press.api.bench.apps", {"name": site.get("group", "")}
                        )
                    )
                    or []
                )
                site_apps = (
                    unwrap(
                        cloud_post("press.api.site.installed_apps", {"name": site_name})
                    )
                    or []
                )

                for a in bench_apps:
                    doc.append("installed", {"app_name": a.get("name", "")})
                for a in site_apps:
                    doc.append(
                        "custom",
                        {
                            "app_name": a.get("app", ""),
                            "title": a.get("repository", ""),
                        },
                    )
            else:
                doc.new_apps = json.dumps(shared_options)
                site_apps = (
                    unwrap(
                        cloud_post("press.api.site.installed_apps", {"name": site_name})
                    )
                    or []
                )
                for a in site_apps:
                    doc.append(
                        "custom",
                        {
                            "app_name": a.get("repository", ""),
                            "title": a.get("app", ""),
                        },
                    )

            doc.insert(ignore_permissions=True)
            frappe.db.commit()

    except Exception:
        frappe.log_error("sync_site", frappe.get_traceback())


# --------------------------------------------------------------------------- #
#  Private helpers
# --------------------------------------------------------------------------- #


def _format_duration(completion_str: str, duration_str: str):
    """
    Format a completion timestamp and duration string into human-readable values.
    Returns (pretty_time, formatted_duration).
    """
    from frappe.utils import pretty_date, format_duration
    from datetime import datetime, timedelta

    try:
        try:
            dt = datetime.strptime(completion_str, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            dt = datetime.strptime(completion_str, "%Y-%m-%d %H:%M:%S")

        diff = datetime.now() - dt
        pretty_time = str(diff.days) if diff.days >= 1 else pretty_date(dt)

        parts = list(map(float, duration_str.split(":")))
        total_seconds = timedelta(
            hours=parts[0], minutes=parts[1], seconds=parts[2]
        ).total_seconds()
        return pretty_time, format_duration(total_seconds)
    except Exception:
        return "", ""
