// Copyright (c) 2024, Tridots Tech and contributors
// For license information, please see license.txt

frappe.ui.form.on('Go1 FCloud Server', {
	refresh: function(frm) {
		frm.add_custom_button("New Bench",function(){
			frappe.model.open_mapped_doc({
				method: "go1_fcloud.go1_fcloud.api.new_bench_from_server",
				frm: frm
			})
		})
	}
});
