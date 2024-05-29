frappe.listview_settings['Go1 FCloud Invoice'] = {

    onload(listview) {
        // triggers once before the list is loaded
        listview.page.add_inner_button('Sync Invoices', function (frm) {
            frappe.call({
                method: "go1_fcloud.go1_fcloud.doctype.go1_fcloud_invoices.go1_fcloud_invoices.sync_invoices_queue",
                async: true,
                freeze: true,
                freeze_message: "Syncing Invoices From Frappe Cloud",
                callback: function (r) {
                    frappe.msgprint("Invoices Sync Scheduled Succesfully")
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