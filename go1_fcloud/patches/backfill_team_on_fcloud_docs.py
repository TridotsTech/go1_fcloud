"""Backfill team field on existing Go1 FCloud Site/Bench/Server records.

Reads x_press_team_id from Go1 FCloud Configuration and sets it on all
records where team is NULL or empty.

If the column does not exist yet, the patch skips silently — the next
sync will populate the field.
"""

import frappe


def execute():
    team_id = frappe.db.get_single_value("Go1 FCloud Configuration", "x_press_team_id")
    if not team_id:
        return

    for dt in ("Go1 FCloud Site", "Go1 FCloud Bench", "Go1 FCloud Server"):
        if not frappe.db.has_column(dt, "team"):
            continue
        tbl = frappe.qb.DocType(dt)
        (
            frappe.qb.update(tbl)
            .set(tbl.team, team_id)
            .where(
                (tbl.team.isnull()) | (tbl.team == "")
            )
        ).run()
