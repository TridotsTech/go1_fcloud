frappe.listview_settings['Go1 FCloud Invoice'] = {

    onload(listview) {
        // triggers once before the list is loaded
        listview.page.add_inner_button('Sync Invoice', function (frm) {
            frappe.call({
                method: "go1_fcloud.go1_fcloud.doctype.go1_fcloud_invoice.go1_fcloud_invoice.sync_invoices_queue",
                async: true,
                callback: function (r) {
                    frappe.msgprint("FCloud Invoice Synced Scheduled Successfully")
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
