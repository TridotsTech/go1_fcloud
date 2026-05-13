# Copyright (c) 2024, Tridots Tech and contributors
# For license information, please see license.txt
#
# go1_fcloud_bench.py — Bench (Release Group) DocType controller.
#
# Key API changes vs. original:
#   - press.api.bench.get           now uses @protected → still callable
#   - press.api.bench.apps          now uses @protected → still callable
#   - press.api.bench.deploy_information  @protected → still callable
#   - press.api.bench.deploy_and_update   @protected → still callable
#   - press.api.bench.rebuild       @protected(Bench) → needs bench version ID
#   - press.api.bench.restart       @protected(Bench) → needs bench version ID
#   - press.api.bench.versions      @protected → still callable
#   - press.api.bench.candidates    @protected → still callable
#   - press.api.bench.candidate     @protected(Deploy Candidate) → still callable
#   - press.api.bench.jobs          @protected → still callable
#   - press.api.bench.running_jobs  NEW endpoint → preferred for active jobs
#   - press.api.bench.archive       @protected → still callable
#   - press.api.bench.rename        @protected → still callable
#   - press.api.bench.add_apps      @protected → still callable
#   - press.api.bench.remove_app    @protected → still callable
#   - press.api.bench.update_all_sites @protected → still callable
#   - press.api.bench.regions       @protected → still callable
#   - press.api.bench.generate_certificate @protected → still callable
#   - press.api.bench.certificate   @protected → still callable
#   - press.api.app.new             → still available
#   - press.api.github.*            → unchanged
#   - press.api.client.get_list     → still available
#   - get_token / make_request      → removed; use go1_fcloud.utils

import frappe
import json
from frappe.model.document import Document
from go1_fcloud.utils import cloud_get, cloud_post, unwrap


class Go1FCloudBench(Document):

    # ------------------------------------------------------------------ #
    #  Project mapping helpers
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def set_bench_id(self, args):
        """Link this bench to a Frappe Project record."""
        try:
            proj = frappe.get_doc("Project", args["project_name"])
            if not proj.custom_bench:
                proj.custom_bench = args["name"]
                proj.save(ignore_permissions=True)
        except Exception:
            frappe.log_error("set_bench_id", frappe.get_traceback())

    # ------------------------------------------------------------------ #
    #  Bench creation / options
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def get_bench_options(self):
        """
        Return options for creating a new bench (Frappe versions, clusters, etc.)
        Endpoint: press.api.bench.options
        """
        try:
            return cloud_post("press.api.bench.options")
        except Exception:
            frappe.log_error("get_bench_options", frappe.get_traceback())

    @frappe.whitelist()
    def create_bench(self, args):
        """
        Create a new Release Group / bench on Frappe Cloud.
        Endpoint: press.api.bench.new
        """
        try:
            bench_apps = []
            for app in args.apps:
                bench_apps.append(
                    {
                        "name": (
                            app.get("title") if isinstance(app, dict) else app["title"]
                        ),
                        "source": (
                            app.get("name1") if isinstance(app, dict) else app["name1"]
                        ),
                    }
                )

            payload = {
                "bench": {
                    "title": args.title,
                    "version": args.version,
                    "cluster": args.region if not getattr(args, "server", None) else "",
                    "server": getattr(args, "server", ""),
                    "saas_app": "",
                    "apps": bench_apps,
                }
            }
            response = cloud_post("press.api.bench.new", payload)
            bench_id = unwrap(response)
            if bench_id:
                return cloud_post("press.api.bench.get", {"name": bench_id})
            return response
        except Exception:
            frappe.log_error("create_bench", frappe.get_traceback())

    @frappe.whitelist()
    def drop_bench(self, args):
        """
        Archive (delete) the bench.
        Endpoint: press.api.bench.archive
        """
        try:
            return cloud_post("press.api.bench.archive", {"name": args.title})
        except Exception:
            frappe.log_error("drop_bench", frappe.get_traceback())

    @frappe.whitelist()
    def edit_title(self, args):
        """
        Rename the bench.
        Endpoint: press.api.bench.rename
        """
        try:
            return cloud_post(
                "press.api.bench.rename", {"name": args.name, "title": args.title}
            )
        except Exception:
            frappe.log_error("edit_title", frappe.get_traceback())

    # ------------------------------------------------------------------ #
    #  App management on bench
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def get_installed_apps(self, args):
        """
        List apps installed in a Release Group.
        Endpoint: press.api.bench.apps
        """
        try:
            return unwrap(cloud_post("press.api.bench.apps", {"name": args.title}))
        except Exception:
            frappe.log_error("get_installed_apps", frappe.get_traceback())

    @frappe.whitelist()
    def show_installed_apps(self, args):
        """Alias for get_installed_apps — returns full response."""
        try:
            return cloud_post("press.api.bench.apps", {"name": args.name})
        except Exception:
            frappe.log_error("show_installed_apps", frappe.get_traceback())

    @frappe.whitelist()
    def update_app(self, args):
        """
        Add / update apps in the bench.
        Endpoint: press.api.bench.add_apps
        """
        try:
            apps = [
                {
                    "app": a.get("app") if isinstance(a, dict) else a["app"],
                    "source": a.get("source") if isinstance(a, dict) else a["source"],
                }
                for a in args.apps
            ]
            return cloud_post(
                "press.api.bench.add_apps", {"name": args.name, "apps": apps}
            )
        except Exception:
            frappe.log_error("update_app", frappe.get_traceback())

    @frappe.whitelist()
    def remove_app(self, args):
        """
        Remove an app from the bench.
        Endpoint: press.api.bench.remove_app
        """
        try:
            return cloud_post(
                "press.api.bench.remove_app", {"name": args.id, "app": args.name}
            )
        except Exception:
            frappe.log_error("remove_app", frappe.get_traceback())

    # ------------------------------------------------------------------ #
    #  GitHub / custom app integration
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def get_git_repo(self):
        """List GitHub app installations for the team."""
        try:
            return cloud_post("press.api.github.options")
        except Exception:
            frappe.log_error("get_git_repo", frappe.get_traceback())

    @frappe.whitelist()
    def available_app(self, args):
        """Check if a GitHub repository is a valid Frappe app."""
        try:
            return cloud_post(
                "press.api.github.repository",
                {
                    "installation": args.id,
                    "name": args.name,
                    "owner": args.owner,
                },
            )
        except Exception:
            frappe.log_error("available_app", frappe.get_traceback())

    @frappe.whitelist()
    def validate_app(self, args):
        """Validate a GitHub branch for a Frappe app."""
        try:
            return cloud_post(
                "press.api.github.app",
                {
                    "branch": args.branch,
                    "installation": args.install_id,
                    "owner": args.owner,
                    "repository": args.repo,
                },
            )
        except Exception:
            frappe.log_error("validate_app", frappe.get_traceback())

    @frappe.whitelist()
    def add_custom_app(self, args):
        """
        Add a custom app from GitHub to the bench.
        Endpoint: press.api.app.new
        """
        try:
            return cloud_post(
                "press.api.app.new",
                {
                    "app": {
                        "branch": args.branch,
                        "github_installation_id": args.install_id,
                        "group": args.bench,
                        "name": args.name,
                        "repository_url": args.url,
                        "title": args.title,
                    }
                },
            )
        except Exception:
            frappe.log_error("add_custom_app", frappe.get_traceback())

    # ------------------------------------------------------------------ #
    #  Deploy
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def deploy_bench(self, args):
        """
        Check for available updates and return deploy information.
        Endpoint: press.api.bench.deploy_information
        Returns a tuple: [{deploys: [...]}, {versions: [...]}]
        """
        try:
            deploys = self._get_deploy_info(args)
            versions = unwrap(
                cloud_post("press.api.bench.versions", {"name": args.title})
            )
            return [{"deploys": deploys}, {"versions": versions}]
        except Exception:
            frappe.log_error("deploy_bench", frappe.get_traceback())

    def _get_deploy_info(self, args):
        """
        Internal: fetch deploy_information and format update list.
        Endpoint: press.api.bench.deploy_information
        """
        rel_msg = unwrap(
            cloud_post("press.api.bench.deploy_information", {"name": args.title})
        )
        if not rel_msg or not rel_msg.get("update_available"):
            frappe.throw("Bench is already up to date. No deploy needed.")

        updates = []
        for app in rel_msg.get("apps", []):
            for release in app.get("releases", []):
                if release.get("name") == app.get("next_release"):
                    updates.append(
                        {
                            "title": app.get("title"),
                            "app": app.get("app"),
                            "repo": app.get("repository"),
                            "owner": app.get("repository_owner"),
                            "branch": app.get("branch"),
                            "status": release.get("status"),
                            "tag": release.get("tag"),
                            "current_tag": app.get("current_tag"),
                            "next_release": app.get("next_release"),
                        }
                    )

        for removed in rel_msg.get("removed_apps", []):
            updates.append(
                {
                    "title": removed.get("title"),
                    "status": "Will Be Uninstalled",
                    "tag": "remove",
                }
            )

        return updates

    @frappe.whitelist()
    def deploy_and_update(self, args):
        """
        Deploy selected app updates and migrate sites.
        Endpoint: press.api.bench.deploy_and_update
        """
        try:
            apps, sites = [], []
            for item in args.message[0].get("app", []):
                if "app" in item:
                    apps.append({"app": item["app"], "release": item["next_release"]})
            for s in args.message[0].get("site", []):
                sites.append(
                    {
                        "name": s.get("name"),
                        "bench": s.get("bench"),
                        "server": s.get("server"),
                        "skip_failing_patches": 0,
                        "skip_backups": 0,
                    }
                )
            return cloud_post(
                "press.api.bench.deploy_and_update",
                {"name": args.title, "apps": apps, "sites": sites},
            )
        except Exception:
            frappe.log_error("deploy_and_update", frappe.get_traceback())

    @frappe.whitelist()
    def update_site(self, args):
        """
        Trigger update on all sites in the bench.
        Endpoint: press.api.bench.update_all_sites
        """
        try:
            return cloud_post("press.api.bench.update_all_sites", {"name": args.id})
        except Exception:
            frappe.log_error("update_site", frappe.get_traceback())

    # ------------------------------------------------------------------ #
    #  Bench server operations  (restart / rebuild need bench VERSION id)
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def bench_restart(self, args):
        """
        Restart bench workers.
        NOTE: press.api.bench.restart takes the *Bench* (version) ID,
        not the Release Group ID. We fetch it from press.api.bench.versions first.
        Endpoint: press.api.bench.restart
        """
        try:
            versions = (
                unwrap(cloud_post("press.api.bench.versions", {"name": args.title}))
                or []
            )
            if not versions:
                frappe.throw("No deployed bench version found. Deploy the bench first.")
            bench_version_id = versions[0].get("name")
            return cloud_post("press.api.bench.restart", {"name": bench_version_id})
        except frappe.ValidationError:
            raise
        except Exception:
            frappe.log_error("bench_restart", frappe.get_traceback())

    @frappe.whitelist()
    def bench_build(self, args):
        """
        Rebuild (re-deploy) bench assets.
        NOTE: press.api.bench.rebuild also takes the *Bench* (version) ID.
        Endpoint: press.api.bench.rebuild
        """
        try:
            versions = (
                unwrap(cloud_post("press.api.bench.versions", {"name": args.title}))
                or []
            )
            if not versions:
                frappe.throw("No deployed bench version found. Deploy the bench first.")
            bench_version_id = versions[0].get("name")
            return cloud_post("press.api.bench.rebuild", {"name": bench_version_id})
        except frappe.ValidationError:
            raise
        except Exception:
            frappe.log_error("bench_build", frappe.get_traceback())

    @frappe.whitelist()
    def versions(self, args):
        """
        Return deployed bench versions.
        Endpoint: press.api.bench.versions
        """
        try:
            name = args.id if hasattr(args, "id") and args.id else args.title
            return cloud_post("press.api.bench.versions", {"name": name})
        except Exception:
            frappe.log_error("versions", frappe.get_traceback())

    # ------------------------------------------------------------------ #
    #  SSH certificate
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def get_certificate(self, args):
        """
        Add the team's SSH key and generate an SSH certificate for the bench.
        Endpoints: press.api.account.add_key + press.api.bench.generate_certificate
        """
        try:
            ssh_key = frappe.db.get_single_value("Go1 FCloud Settings", "ssh_key")
            if not ssh_key:
                frappe.throw("Set your public SSH key in Go1 FCloud Settings first.")

            add_key_resp = cloud_post("press.api.account.add_key", {"key": ssh_key})
            if "exception" in (add_key_resp or {}):
                frappe.throw(add_key_resp["exception"])

            cloud_post("press.api.bench.generate_certificate", {"name": args.title})
            frappe.msgprint(
                "Certificate generated. Click 'Get SSH Access' to retrieve it. "
                "Valid for 6 hours."
            )
        except frappe.ValidationError:
            raise
        except Exception:
            frappe.log_error("get_certificate", frappe.get_traceback())

    @frappe.whitelist()
    def certificate(self, args):
        """
        Retrieve the SSH certificate and construct the SSH command.
        Endpoints: press.api.bench.certificate + press.api.bench.versions
                   + press.api.client.get_list
        """
        try:
            cert_resp = unwrap(
                cloud_post("press.api.bench.certificate", {"name": args.title})
            )
            if not cert_resp:
                frappe.throw("Generate the SSH token first.")

            if "exception" in (cert_resp or {}):
                frappe.throw("No sites available on this bench.")

            if not cert_resp.get("ssh_certificate"):
                frappe.throw(
                    "Try again after 15–30 minutes for the certificate to be ready."
                )

            # Get proxy server from bench versions
            cmd_resp = (
                unwrap(cloud_post("press.api.bench.versions", {"name": args.title}))
                or []
            )

            # Get site bench name for SSH command
            site_bench_resp = (
                unwrap(
                    cloud_post(
                        "press.api.client.get_list",
                        {
                            "doctype": "Site",
                            "fields": ["bench"],
                            "filters": {
                                "group": self.id,
                                "skip_team_filter_for_system_user": True,
                            },
                            "order_by": "creation desc, bench desc",
                            "limit_page_length": 1,
                        },
                    )
                )
                or []
            )

            if not cmd_resp or not site_bench_resp:
                frappe.throw(
                    "Could not build SSH command. Is there a site on this bench?"
                )

            site_bench = site_bench_resp[0].get("bench", "")
            proxy = cmd_resp[0].get("proxy_server", "")
            ssh_command = f"ssh {site_bench}@{proxy} -p 2222"

            return [
                {"certificate": cert_resp["ssh_certificate"], "command": ssh_command}
            ]
        except frappe.ValidationError:
            raise
        except Exception:
            frappe.log_error("certificate", frappe.get_traceback())

    # ------------------------------------------------------------------ #
    #  Jobs / Deploys / Status
    # ------------------------------------------------------------------ #

    @frappe.whitelist()
    def get_all_site(self, args):
        """
        Return sites, running jobs, and recent deploys for this bench.
        Endpoints: press.api.client.get_list, press.api.bench.running_jobs,
                   press.api.bench.candidates, press.api.bench.candidate
        """
        try:
            res = [{"jobs": []}, {"deploys": []}]

            # Sites on bench
            sites = (
                unwrap(
                    cloud_post(
                        "press.api.client.get_list",
                        {
                            "doctype": "Site",
                            "fields": [
                                "name",
                                "status",
                                "bench",
                                "host_name",
                                "plan.plan_title as plan_title",
                                "plan.price_usd as price_usd",
                                "plan.price_inr as price_inr",
                                "cluster.image as cluster_image",
                                "cluster.title as cluster_title",
                            ],
                            "filters": {
                                "group": self.id,
                                "skip_team_filter_for_system_user": True,
                            },
                            "order_by": "creation desc, bench desc",
                            "limit_page_length": 99999,
                        },
                    )
                )
                or []
            )
            res.append(sites)

            # Running bench jobs (CHANGE: use running_jobs + jobs for history)
            running = (
                unwrap(cloud_post("press.api.bench.running_jobs", {"name": args.title}))
                or []
            )
            for job in running:
                steps = [
                    {
                        "name": s.get("step_name", ""),
                        "status": s.get("status", ""),
                        "output": s.get("output", ""),
                    }
                    for s in job.get("steps", [])
                ]
                fmt_time, duration = _format_duration(
                    job.get("creation", ""), job.get("duration", "")
                )
                res[0]["jobs"].append(
                    {
                        "type": job.get("job_type", ""),
                        "start": job.get("start"),
                        "end": job.get("end"),
                        "status": job.get("status", ""),
                        "steps": steps,
                        "duration": duration,
                        "completion": job.get("creation"),
                    }
                )

            # Deploy candidates
            deploys_raw = (
                unwrap(
                    cloud_post(
                        "press.api.bench.candidates",
                        {
                            "doctype": "Deploy Candidate",
                            "filters": {"group": args.title},
                            "limit_page_length": 5,
                        },
                    )
                )
                or []
            )
            for dep in deploys_raw:
                detail = (
                    unwrap(
                        cloud_post(
                            "press.api.bench.candidate", {"name": dep.get("name")}
                        )
                    )
                    or {}
                )
                build_steps = [
                    {
                        "name": f"{s.get('stage','')} - {s.get('step','')}",
                        "status": s.get("status", ""),
                        "command": s.get("command"),
                        "output": s.get("output"),
                    }
                    for s in detail.get("build_steps", [])
                ]
                fmt_time, duration = _format_duration(
                    detail.get("build_end", ""), detail.get("build_duration", "")
                )
                res[1]["deploys"].append(
                    {
                        "name": dep.get("name"),
                        "creation": dep.get("creation"),
                        "status": dep.get("status"),
                        "apps": dep.get("apps", []),
                        "steps": build_steps,
                        "completion": fmt_time,
                        "duration": duration,
                    }
                )

            return res
        except Exception:
            frappe.log_error("get_all_site", frappe.get_traceback())

    @frappe.whitelist()
    def bench_jobs(self, args):
        """
        Return recent jobs for the bench.
        CHANGE: prefer press.api.bench.running_jobs over press.api.bench.jobs
        """
        try:
            # Active/recent jobs via running_jobs
            return cloud_post("press.api.bench.running_jobs", {"name": args.title})
        except Exception:
            frappe.log_error("bench_jobs", frappe.get_traceback())

    @frappe.whitelist()
    def get_deploy_site(self, args):
        """Get site details from Frappe Cloud."""
        try:
            return cloud_post("press.api.site.get", {"name": args.id})
        except Exception:
            frappe.log_error("get_deploy_site", frappe.get_traceback())

    @frappe.whitelist()
    def get_site_doc(self, args):
        """Look up local Go1 FCloud Site by URL."""
        return frappe.db.get_value("Go1 FCloud Site", {"url": args.url}, "name")

    @frappe.whitelist()
    def get_permission(self):
        """Get Frappe Cloud account info."""
        try:
            return unwrap(cloud_post("press.api.account.get"))
        except Exception:
            frappe.log_error("get_permission", frappe.get_traceback())

    @frappe.whitelist()
    def get_bench_list(self):
        """List all benches."""
        try:
            return unwrap(cloud_post("press.api.bench.all"))
        except Exception:
            frappe.log_error("get_bench_list", frappe.get_traceback())

    @frappe.whitelist()
    def get_status(self, args):
        """
        Refresh local Go1 FCloud Bench doc from Frappe Cloud.
        Updates: status, apps, deploy history, jobs, linked sites.
        """
        from frappe.utils import pretty_date, format_duration

        try:
            bench_data = unwrap(cloud_post("press.api.bench.get", {"name": args.title}))
            installed_apps = (
                unwrap(cloud_post("press.api.bench.apps", {"name": args.title})) or []
            )
            cloud_data = self.get_all_site(args)

            update_doc = frappe.get_doc("Go1 FCloud Bench", args.doc)
            doc_data = json.loads(update_doc.data or "{}")

            # Find apps matching current version
            version_apps = []
            if bench_data and doc_data:
                current_ver = bench_data.get("version")
                for v in doc_data.get("versions", []):
                    if v.get("name") == current_ver:
                        version_apps = v.get("apps", [])
                        break

            # Rebuild app tables
            update_doc.apps = []
            update_doc.deploy = []
            update_doc.custom = []

            for app in installed_apps:
                update_doc.append(
                    "custom",
                    {
                        "title": app.get("repository", ""),
                        "app_name": app.get("name", ""),
                    },
                )
                for va in version_apps:
                    if va.get("name") == app.get("name"):
                        for source in va.get("sources", []):
                            if source.get("branch") == app.get("branch"):
                                update_doc.append(
                                    "apps",
                                    {
                                        "title": app.get("name", ""),
                                        "name1": source.get("name", ""),
                                    },
                                )

            # Deploy history
            if cloud_data and cloud_data[1].get("deploys"):
                for dep in cloud_data[1]["deploys"]:
                    apps_str = ",".join(dep.get("apps", []))
                    update_doc.append(
                        "deploy",
                        {
                            "title": dep.get("name"),
                            "created_on": dep.get("creation"),
                            "apps": apps_str,
                            "status": dep.get("status"),
                            "steps": json.dumps(dep.get("steps", []), indent=2),
                            "completed": dep.get("completion") or None,
                            "duration": dep.get("duration") or 0,
                        },
                    )

            # Bench status
            if bench_data:
                update_doc.status = bench_data.get("status", "")

            # Jobs
            if cloud_data and cloud_data[0].get("jobs"):
                update_doc.jobs = []
                for job in cloud_data[0]["jobs"]:
                    update_doc.append(
                        "jobs",
                        {
                            "title": job.get("type", ""),
                            "start": job.get("start"),
                            "end": job.get("end"),
                            "status": job.get("status"),
                            "steps": json.dumps(job.get("steps", []), indent=2),
                            "completed": job.get("completion") or None,
                            "duration": job.get("duration") or None,
                        },
                    )

            # Linked sites
            if len(cloud_data) > 2 and cloud_data[2]:
                update_doc.linked_sites = []
                for site in cloud_data[2]:
                    update_doc.append("linked_sites", {"sites": site.get("name", "")})

            update_doc.save(ignore_permissions=True)
            return "Updated"

        except Exception:
            frappe.log_error("get_status (bench)", frappe.get_traceback())


# --------------------------------------------------------------------------- #
#  Module-level sync (bench)
# --------------------------------------------------------------------------- #


@frappe.whitelist()
def sync_bench_enqueue():
    """Enqueue long-running bench sync from Frappe Cloud."""
    try:
        frappe.enqueue(sync_bench, queue="long")
    except Exception:
        frappe.log_error("sync_bench_enqueue", frappe.get_traceback())


@frappe.whitelist()
def sync_bench():
    """Pull all benches from Frappe Cloud and create/update local docs."""
    from go1_fcloud.utils import cloud_post, unwrap

    try:
        cloud_benches = (
            unwrap(
                cloud_post(
                    "press.api.bench.all",
                    {"bench_filter": {"status": "All", "tag": ""}},
                )
            )
            or []
        )
        bench_opts = unwrap(cloud_post("press.api.bench.options")) or {}

        local_benches = frappe.get_all(
            "Go1 FCloud Bench", filters={"is_dropped": 0}, fields=["bench", "name"]
        )
        local_titles = {b["bench"] for b in local_benches}

        for bench in cloud_benches:
            title = bench.get("title", "")
            if title in local_titles:
                continue

            details = _get_cloud_bench_details(bench.get("name", ""))
            doc = frappe.new_doc("Go1 FCloud Bench")
            doc.data = json.dumps(bench_opts, separators=(",", ":"))
            doc.bench = title
            doc.id = bench.get("name", "")
            doc.status = bench.get("status", "")
            doc.version = bench.get("version", "")
            doc.region = details.get("region", "")
            doc.app_data = json.dumps(get_apps(doc.id))

            for app in details.get("installed_apps", []):
                doc.append("apps", {"title": app.get("name", "")})
                doc.append(
                    "custom",
                    {"title": app.get("name", ""), "app_name": app.get("name", "")},
                )

            doc.insert(ignore_permissions=True)
            frappe.db.commit()

    except Exception:
        frappe.log_error("sync_bench", frappe.get_traceback())


def _get_cloud_bench_details(bench_id: str) -> dict:
    from go1_fcloud.utils import cloud_post, unwrap

    regions = unwrap(cloud_post("press.api.bench.regions", {"name": bench_id})) or []
    apps = unwrap(cloud_post("press.api.bench.apps", {"name": bench_id})) or []
    return {
        "region": regions[0].get("name") if regions else "",
        "installed_apps": apps,
    }


@frappe.whitelist()
def get_apps(title):
    """
    List available apps for the bench's Frappe version.
    Endpoint: press.api.bench.versions
    """
    try:
        frappe.log_error("title name", title)
        return cloud_post("press.api.bench.all_apps", {"name": title})
    except Exception:
        frappe.log_error("get_apps", frappe.get_traceback())


# --------------------------------------------------------------------------- #
#  Private helpers
# --------------------------------------------------------------------------- #


def _format_duration(completion_str: str, duration_str: str):
    from frappe.utils import pretty_date, format_duration
    from datetime import datetime, timedelta

    if not completion_str or not duration_str:
        return "", ""
    try:
        try:
            dt = datetime.strptime(completion_str, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            dt = datetime.strptime(completion_str, "%Y-%m-%d %H:%M:%S")
        diff = datetime.now() - dt
        pretty_time = str(diff.days) if diff.days >= 1 else pretty_date(dt)
        parts = list(map(float, duration_str.split(":")))
        secs = timedelta(
            hours=parts[0], minutes=parts[1], seconds=parts[2]
        ).total_seconds()
        return pretty_time, format_duration(secs)
    except Exception:
        return "", ""


@frappe.whitelist()
def deploy(title, message):
    """
    Trigger a deploy for the bench.
    Endpoint: press.api.bench.deploy
    """
    try:
        message = json.loads(message)
        return cloud_post("press.api.bench.deploy", {"name": title, "apps": message})
    except Exception:
        frappe.log_error("deploy", unwrap(frappe.get_traceback()))
