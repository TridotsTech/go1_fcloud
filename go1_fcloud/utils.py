# Copyright (c) 2024, Tridots Tech and contributors
# For license information, please see license.txt
#
# utils.py — Shared utilities for all go1_fcloud doctypes.
# Single source of truth for Frappe Cloud auth and HTTP requests.

import frappe
from frappe import _
import requests

FCLOUD_BASE_URL = "https://cloud.frappe.io"


def get_config():
    """Return the Go1 FCloud Configuration singleton document."""
    try:
        return frappe.get_doc("Go1 FCloud Configuration")
    except Exception:
        frappe.throw(
            _("Go1 FCloud Configuration not found. Please set up API credentials.")
        )


def get_token():
    """
    Return (Authorization-header-value, X-Press-Team-value) from stored config.
    Raises a descriptive error if credentials are missing.
    """
    try:
        cfg = get_config()
        if not cfg.api_key:
            frappe.throw(_(("API Key is not configured in Go1 FCloud Configuration.")))
        secret = cfg.get_password("api_secret")
        if not secret:
            frappe.throw(_("API Secret is not configured in Go1 FCloud Configuration."))
        if not cfg.x_press_team_id:
            frappe.throw(
                _("X-Press-Team ID is not configured in Go1 FCloud Configuration.")
            )
        return f"token {cfg.api_key}:{secret}", cfg.x_press_team_id
    except frappe.ValidationError:
        raise
    except Exception:
        frappe.log_error("get_token", frappe.get_traceback())
        frappe.throw(
            _(
                "Failed to retrieve Frappe Cloud credentials. Check Go1 FCloud Configuration."
            )
        )


def get_headers():
    """Return the HTTP headers dict required for all Frappe Cloud API calls."""
    token, team = get_token()
    return {
        "Authorization": token,
        "X-Press-Team": team,
        "Content-Type": "application/json",
    }


def cloud_request(endpoint: str, method: str = "GET", params: dict = None):
    """
    Make an authenticated request to the Frappe Cloud API.

    Args:
            endpoint: API method path, e.g. "press.api.site.all"
            method:   "GET" or "POST"
            params:   dict of parameters

    Returns:
            Parsed JSON response dict. The Frappe Cloud API always wraps
            results in {"message": ...}, so the full dict is returned.

    Raises:
            frappe.ValidationError on HTTP errors or API exceptions.
    """
    url = f"{FCLOUD_BASE_URL}/api/method/{endpoint}"
    headers = get_headers()

    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=headers, params=params, timeout=30)
        else:
            response = requests.post(url, headers=headers, json=params, timeout=30)

        response.raise_for_status()
        data = response.json()

        # Surface server-side exceptions as Frappe errors
        if "exc" in data or "exception" in data:
            exc_msg = data.get("exception") or data.get("exc") or "Unknown cloud error"
            frappe.log_error(f"cloud_request:{endpoint}", exc_msg)
            frappe.throw(_(f"Frappe Cloud error: {exc_msg}"))

        return data

    except requests.exceptions.Timeout:
        frappe.log_error(f"cloud_request:{endpoint}", "Request timed out")
        frappe.throw(_("Frappe Cloud request timed out. Please try again."))
    except requests.exceptions.ConnectionError:
        frappe.log_error(f"cloud_request:{endpoint}", "Connection error")
        frappe.throw(
            _("Cannot connect to Frappe Cloud. Check your internet connection.")
        )
    except requests.exceptions.HTTPError as e:
        frappe.log_error(f"cloud_request:{endpoint}", str(e))
        frappe.throw(
            _(
                f"Frappe Cloud returned HTTP {response.status_code}: {response.text[:200]}"
            )
        )
    except Exception:
        frappe.log_error(f"cloud_request:{endpoint}", frappe.get_traceback())
        raise


def cloud_get(endpoint: str, params: dict = None):
    """Convenience wrapper for GET requests."""
    return cloud_request(endpoint, "GET", params)


def cloud_post(endpoint: str, params: dict = None):
    """Convenience wrapper for POST requests."""
    return cloud_request(endpoint, "POST", params)


def unwrap(response: dict):
    """
    Extract the 'message' key from a Frappe Cloud response.
    Returns None if the key is missing.
    """
    return response.get("message")
