frappe.listview_settings['Go1 FCloud Bench'] = {

    onload(listview) {
        // triggers once before the list is loaded
        listview.page.add_inner_button('Sync Bench', function (frm) {
            frappe.call({
                method: "go1_fcloud.go1_fcloud.doctype.go1_fcloud_bench.go1_fcloud_bench.sync_bench",
                async: true,
                freeze: true,
                freeze_message: "Syncing Bench From Frappe Cloud",
                callback: function (r) {
                    frappe.msgprint("FCloud Bench Synced Successfully")
                    setTimeout(function () {
                        var dialog = $('.modal:visible')
                        if (dialog.length > 0) {
                            dialog.modal('hide')
                        }
                    }, 2000)
                }
            })
        });
    }
}