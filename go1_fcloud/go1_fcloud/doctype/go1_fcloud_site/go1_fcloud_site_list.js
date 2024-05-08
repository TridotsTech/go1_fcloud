frappe.listview_settings['Go1 FCloud Site'] = {

  onload(listview) {
    // triggers once before the list is loaded
    listview.page.add_inner_button('Sync Site', function (frm) {
      frappe.call({
        method: "go1_fcloud.go1_fcloud.doctype.go1_fcloud_site.go1_fcloud_site.sync_site_enqueue_long",
        async: true,
        freeze: true,
        freeze_message: "Syncing Site From Frappe Cloud",
        callback: function (r) {
          frappe.msgprint("FCloud Site Synced Successfully")
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