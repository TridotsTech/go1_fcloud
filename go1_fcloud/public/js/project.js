frappe.ui.form.on("Project", {
    refresh: function (frm) {
        if (!frm.doc.__islocal) {
            frm.add_custom_button(("Create Bench"), function () {
                frappe.model.open_mapped_doc({
                    method: "go1_fcloud.go1_fcloud.api.create_bench_for_project",
                    frm: frm
                })
            })
        }
    }
})