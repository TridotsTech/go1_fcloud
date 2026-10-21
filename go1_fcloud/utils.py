# Copyright (c) 2024, Tridots Tech and contributors
# For license information, please see license.txt
#
# utils.py — Shared utilities for all go1_fcloud doctypes.
# Single source of truth for Frappe Cloud auth and HTTP requests.

import json

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


def _parse_cloud_error(response):
    """Extract a readable error message from a Frappe Cloud error response.

    Frappe wraps validation errors in _server_messages — a JSON-encoded list
    of JSON-encoded strings (or dicts). This helper digs through that nesting
    so callers see the real message instead of raw escaped JSON.
    """
    try:
        data = response.json()
        server_messages = data.get("_server_messages")
        if server_messages:
            messages = json.loads(server_messages)
            if messages:
                first = messages[0]
                parsed = json.loads(first) if isinstance(first, str) else first
                if isinstance(parsed, dict):
                    return parsed.get("message", str(parsed))
                return str(parsed)
        return data.get("exception") or response.text[:300]
    except Exception:
        return response.text[:300]


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
            # Frappe's JS client (frappe.call) JSON-stringifies nested
            # object/array values before posting.  The server-side handler
            # then calls json.loads() on each string parameter.  If we send
            # raw nested dicts, json.loads(dict) raises TypeError.  Mimic
            # the JS behaviour so the Cloud API receives the types it expects.
            if params:
                params = {
                    k: json.dumps(v) if isinstance(v, (dict, list)) else v
                    for k, v in params.items()
                }
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
        error_msg = _parse_cloud_error(response)
        frappe.log_error(f"cloud_request:{endpoint}", f"{e}\n{error_msg}")
        frappe.throw(_(f"Frappe Cloud error: {error_msg}"))
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
