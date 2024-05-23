frappe.listview_settings['Go1 FCloud Server'] = {
    onload(listview) {
        listview.page.add_inner_button('Sync Server', function (frm) {
            frappe.call({
                method: "go1_fcloud.go1_fcloud.doctype.go1_fcloud_server.go1_fcloud_server.sync_server_enqueue",
                async: true,
                freeze: true,
                freeze_message: "Scheduling Sync Server from Frappe Cloud",
                callback: function (r) {
                    frappe.msgprint("FCloud Server Sync Scheduled Successfully")
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