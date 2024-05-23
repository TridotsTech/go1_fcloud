// Copyright (c) 2024, Raino and contributors
// For license information, please see license.txt

frappe.ui.form.on("Go1 FCloud Bench", {
    validate: function (frm) {
        if (frm.doc.__islocal) {
            var install = frm.doc.apps
            let apps = [], set = []
            if (install[0].title != "frappe") {
                frappe.throw("First App to install on bench is Frappe")
            }
            for (let i of install) {
                apps.push(i.title)
            }
        }
        var install = frm.doc.apps
        let apps = []
        for (let i of install) {
            apps.push(i.title)
        }
        const uniqueSet = new Set(apps);
        let set = Array.from(uniqueSet)
        if ((set.length) != (apps.length)) {
            frappe.throw("Delete duplicate apps")
        }
    },
    before_save: function (frm) {
        let apps = []
        for (let i of frm.doc.apps) {
            apps.push(i.title)
        }
        const uniqueSet = new Set(apps);
        let set = Array.from(uniqueSet)
        if ((set.length) != (apps.length)) {
            frappe.throw("Delete duplicate apps")
        }
        if (frm.doc.id) {
            if (frm.fields_dict.apps.df.hidden == 0) {
                console.log("checking code....")
                frm.fields_dict.apps.df.hidden = 1
                frm.fields_dict.custom.df.hidden = 0
                frm.refresh_field("apps")
                frm.refresh_field("custom")
            }
        }
    },
    refresh: function (frm) {
        let session_roles = frappe.user_roles

        if (frm.doc.id && !frm.doc.__islocal && !frm.doc.is_dropped) {
            frm.add_custom_button(__("Get status"), function () {
                let in_apps = []
                let install_app
                frappe.call({
                    doc: frm.doc,
                    method: "get_status",
                    args: {
                        "title": frm.doc.id,
                        "doc":frm.doc.name
                    },
                    async: true,
                    freeze: true,
                    freeze_message: "Retrieving Status....",
                    callback: function (r) {
                        if (r.message) {
                            frm.refresh()
                            frappe.show_alert('Status Updated');
                            // let status_data = r.message
                            // // console.log(status_data)
                            // var bench = status_data[0].bench.message
                            // // frm.set_value("status", bench.status)
                            // frm.fields_dict.apps.df.hidden = 1
                            // frm.set_value("custom", "")
                            // var apps = status_data[1].installed_apps
                            // //set installed apps
                            // var capps = frm.doc.apps
                            // for (var a of capps) {
                            //     in_apps.push(a.name1)
                            // }
                            // for (var app of apps) {
                            //     if (!in_apps.includes(app.name)) {
                            //         let row = frm.add_child("custom")
                            //             row.title = app.repository,
                            //             row.app_name = app.name
                            //     }
                            // }
                            // frm.refresh_field("custom")
                            // frm.refresh_field("apps")

                            //Deploys , Jobs and Sites Update

                            // frm.set_value("linked_sites", "")
                            // frm.set_value("jobs", "")
                            // frm.set_value("deploy", "")
                            // let data = status_data[2].sites
                            // for (let job of data[0].jobs) {
                            //     frm.add_child("jobs", {
                            //         "title": job.type,
                            //         "start": job.start,
                            //         "end": job.end,
                            //         "status": job.status,
                                    
                            //     })
                            // }
                           
                            // for (let dep of data[1].deploys) {
                            //     let app_name = ""
                            //     for (let a of dep.apps) {
                            //         app_name += a + ","
                            //     }
                            //     let steps=[]
                            //     for(let j of dep.steps){
                            //         steps.push(j)
                            //     }
                            
                            //     frm.add_child("deploy", {
                            //         "title": dep.name,
                            //         "created_on": dep.creation,
                            //         "status": dep.status,
                            //         "apps": app_name.substring(0, app_name.length - 1),
                            //         "steps":JSON.stringify(dep.steps)
                            //     })
                            //     // console.log(dep.steps)
                            //     // console.log(typeof(dep.steps))
                            // }
                            // for (let s of data[2]) {
                            //     if (frm.doc.id == s["group"]) {
                            //         let row = frm.add_child("linked_sites")
                            //         row.sites = s["name"]
                            //     }
                            // }
                            // frm.refresh_field("deploy")
                            // frm.save()
                            // frm.save()
                        }
                    }
                })

            }, __("Menu"))
            //Edit Title
            frm.add_custom_button("Edit Title", function () {
                let d = new frappe.ui.Dialog({
                    title: "Edit Bench Title",
                    fields: [{
                        "label": "Title Name",
                        "fieldname": "title",
                        "fieldtype": "Data",
                        "reqd": 1
                    }],
                    primary_action_label: 'Submit',
                    primary_action(values) {
                        frappe.call({
                            doc: frm.doc,
                            method: "edit_title",
                            args: {
                                "name": frm.doc.id,
                                "title": values.title
                            },
                            callback: function (r) {
                                if (Object.keys(r.message) == 0) {
                                    frm.set_value("bench", values.title)
                                    frm.save()
                                }
                            }
                        })
                        // console.log(values.title)
                        d.hide()
                    }
                })
                d.show()
            }, __("Menu"))
        } else {
            if (!frm.doc.__islocal && !frm.doc.id && !frm.doc.is_dropped) {
                frm.add_custom_button(__("Bench"), function () {
                    frappe.call({
                        doc: frm.doc,
                        method: "create_bench",
                        args: {
                            "title": frm.doc.bench,
                            'version': frm.doc.version,
                            'region': frm.doc.region,
                            "apps": frm.doc.apps,
                            "server":frm.doc.server_id
                        },
                        async: true,
                        freeze:true,
                        freeze_message:"Creating Bench...",
                        callback: function (r) {
                            var bench = r.message.message
                            frm.set_value("id", bench.name)
                            frm.set_value("status", bench.status)
                            frm.save()
                        }
                    })
                }, __("Create"))
            }
        }



        if (!frm.doc.__islocal && frm.doc.id && !frm.doc.is_dropped) {
            let sites
            frm.add_custom_button(("Latest Pulls"), function () {
                var update, sites
                let show_updates = [], in_sites = []
                frappe.call({
                    doc: frm.doc,
                    method: "deploy_bench",
                    args: {
                        "title": frm.doc.id,
                    },
                    async: true,
                    freeze: true,
                    freeze_message: "Fetching Data.....",
                    callback: function (r) {
                        if (r.message) {
                            let return_data = r.message
                            // console.log(return_data)
                            update = return_data[0].deploys
                            for (var u of update) {
                                // console.log(u.title)
                                // console.log(u.branch)
                                // console.log(u.tag)
                                let update
                                if (u.status == "Draft" || u.current_tag == null) {
                                    if (u.tag == null) {
                                        // console.log("status in  null")
                                        update = { "label": `${u.title}`, "fieldtype": "Check", "fieldname": `${u.title}` }
                                        show_updates.push(update)
                                    }
                                    else if (u.tag == "remove") {
                                        // console.log("satatus in uninstalled")
                                        update = { "label": `${u.title}` + " " + `(${u.status})`, "fieldtype": "Check", "fieldname": `${u.title}` }
                                        show_updates.push(update)
                                    } else {
                                        // console.log("status in  not null")
                                        update = { "label": `${u.title}` + " " + `(First Deploy)` + " " + `${u.tag}`, "fieldtype": "Check", "fieldname": `${u.title}` }
                                        show_updates.push(update)
                                    }
                                } else {
                                    // console.log("status not in if draft")
                                    update = { "label": `${u.title}` + " " + `${u.current_tag} --> ${u.tag}`, "fieldtype": "Check", "fieldname": `${u.title}` }
                                    show_updates.push(update)
                                }

                            }
                            //versions
                            sites = return_data[1].versions
                            for (let res of return_data[1].versions) {
                                for (let site of res.sites) {
                                    // console.log("site")
                                    // console.log(site)
                                    in_sites.push({ 'label': site.name, "fieldname": site.name, "fieldtype": "Check" })
                                }
                            }
                            
                        }
                        var result = []
                            if (update) {
                                let d = new frappe.ui.Dialog({
                                    title: "Updates Available",
                                    fields: [{
                                        "label": "Select Apps To Update",
                                        "fieldtype": "HTML",
                                        "options": "<h5><b>Select Apps</b></h5>"
                                    }].concat(show_updates).concat([
                                        {
                                            "label": "Select Apps To Update",
                                            "fieldtype": "HTML",
                                            "options": "<h5><b>Select Sites</b></h5>"
                                        }
                                    ]).concat(in_sites),
                                    primary_action_label: 'Submit',
                                    primary_action(values) {
                                        let argument = [{ "site": [], "app": [] }]
                                        for (var [key, v] of Object.entries(values)) {
                                            if (v == 1) {
                                                let r = { "key": `${key}`, "value": `${v}` }
                                                result.push(r)
                                            }
                                        }

                                        for (let r of result) {
                                            for (let u of update) {
                                                if (r.key == u.title) {
                                                    argument[0].app.push(u)
                                                }
                                            }
                                            for (let i of sites) {
                                                for (let site of i.sites) {
                                                    if (site.name == r.key) {
                                                        frappe.call({
                                                            doc: frm.doc,
                                                            method: "get_deploy_site",
                                                            async: false,
                                                            args: {
                                                                "id": site.name
                                                            },
                                                            callback: function (r) {
                                                                argument[0].site.push({
                                                                    "server": r.message.message.server,
                                                                    "name": r.message.message.name,
                                                                    "bench": site.bench
                                                                })

                                                            }
                                                        })
                                                    }
                                                }
                                            }
                                        }

                                        frappe.call({
                                            doc: frm.doc,
                                            method: "deploy_and_update",
                                            args: {
                                                "message": argument,
                                                "title": frm.doc.id
                                            },
                                            async: true,
                                            freeze: true,
                                            freeze_message: "Deploying...",
                                            callback: function (r) {
                                                if (r.message) {
                                                    // console.log(r.message.message)
                                                    frappe.msgprint("Bench Deployed Succesfully , Click <b>Get Status</b> to know the status of deploy")
                                                }
                                            }
                                        })
                                        d.hide();
                                    }
                                })
                                d.show()
                            }
                    }
                })



            }, __("Updates"))
        }


        if (!frm.doc.__islocal && frm.doc.id && !frm.doc.is_dropped) {
            if (frm.doc.status == "Active") {
                frm.add_custom_button("New Site", function () {
                    frappe.model.open_mapped_doc({
                        method: "go1_fcloud.go1_fcloud.api.new_site",
                        frm: frm
                    })
                }, __("Create"))
            }
        }


        if (!frm.doc.__islocal && frm.doc.id && !frm.doc.is_dropped) {
            frm.add_custom_button(("Bench Restart"), function () {
                frappe.confirm("Do You Want to Restart Bench",
                    () => {
                        frappe.call({
                            doc: frm.doc,
                            method: "bench_restart",
                            args: {
                                "title": frm.doc.id
                            },
                            async: true,
                            freeze: true,
                            freeze_message: "Restarting bench <b>" + frm.doc.bench + "</b>",
                            callback: function (r) {
                                if (Object.keys(r.message) == 0) {
                                    frappe.msgprint("Bench Restarted")
                                }
                            }
                        })
                    })
            }, __("Menu"))
        }



        if (frm.doc.id && !frm.doc.__islocal && !frm.doc.is_dropped) {
            if (frm.doc.linked_sites.length > 0) {
                frm.add_custom_button("Generate SSH Certificate", function () {
                    frappe.call({
                        doc: frm.doc,
                        method: "get_certificate",
                        args: {
                            "title": frm.doc.id
                        },
                        async: true,
                        freeze: true,
                        freeze_message: "Generating SSH Certificate....."
                    })
                }, __("SSH Certificate"))
                frm.add_custom_button("Get SSH Access", function () {
                    frappe.call({
                        doc: frm.doc,
                        method: "certificate",
                        args: {
                            "title": frm.doc.id
                        },
                        async: true,
                        freeze: true,
                        freeze_message: "Retrieveing SSH Certificate for bench <b>" + frm.doc.bench + "</b>",
                        callback: function (r) {
                            if (r.message) {
                                // console.log(r.message)
                                var key = r.message
                                // console.log(key)
                                // console.log(key.ssh_certificate)
                                frm.set_value("ssh_certificate", "echo '" + key[0].certificate + " '> ~/.ssh/id_rsa-cert.pub")
                                // var command = "ssh " + key[0].command + "@n1-mumbai.frappe.cloud -p 2222"
                                // // console.log(command)
                                frm.set_value("command", key[0].command)
                                frm.save()
                            }
                        }
                    })
                }, __("SSH Certificate"))
            }
        }



        if (!frm.doc.__islocal && frm.doc.id && !frm.doc.is_dropped) {
            frm.add_custom_button("Add App", function () {
                frm.set_df_property("apps", "read_only", 0)
                frm.set_df_property("apps", "hidden", 0)
                frm.set_df_property("custom", "hidden", 1)
                // frm.set_df_property("update_app", "hidden", 0)
                // frm.add_custom_button("Update Later", function () {
                //     frm.set_df_property("apps", "read_only", 1)
                //     frm.set_df_property("apps", "hidden", 1)
                //     frm.set_df_property("custom", "hidden", 0)
                //     // frm.set_df_property("update_app", "hidden", 1)
                //     frm.remove_custom_button("Update Later")
                // })
                frappe.msgprint("Apps table enabled to add apps")
            }, __("Menu"))

            frm.add_custom_button("Update Apps", function () {
                let apps = [], in_apps = []
                for (let i of frm.doc.apps) {
                    apps.push(i.title)
                }
                const uniqueSet = new Set(apps);
                let set = Array.from(uniqueSet)
                if ((set.length) != (apps.length)) {
                    frappe.throw("Delete duplicate apps")
                }
                let custom = []
                for (let app of frm.doc.custom) {
                    // console.log(app.app_name)
                    custom.push(app.app_name)
                }
                // console.log(custom)
                // console.log(custom.length)
                if (custom.length > 0) {
                    let args = []
                    for (let a of frm.doc.apps) {
                        if (!custom.includes(a.title)) {
                            // console.log(a.title)
                            // console.log(a.name1)
                            args.push({ "app": a.title, "source": a.name1 })
                        }
                    }
                    // console.log(args)
                    // console.log(args.length)
                    if (args.length > 0) {
                        frappe.call({
                            doc: frm.doc,
                            method: "update_app",
                            async: false,
                            args: {
                                "name": frm.doc.id,
                                "apps": args
                            }, callback: function (r) {
                                // console.log("callback update")
                            }
                        })
                        // frm.set_df_property("update_app", "hidden", 1)
                        //get list of apps
                        frappe.call({
                            doc: frm.doc,
                            method: "get_installed_apps",
                            args: {
                                "title": frm.doc.id
                            },
                            async: false,
                            callback: function (r) {
                                frm.set_value("custom", "")
                                var apps = r.message
                                // console.log(apps)
                                var capps = frm.doc.apps
                                for (var a of capps) {
                                    // console.log(a.name1)
                                    in_apps.push(a.name1)
                                }
                                for (var app of apps) {
                                    // console.log("bench apps")
                                    // console.log(app)
                                    if (!in_apps.includes(app.name)) {
                                        // console.log(app.name)
                                        // console.log(app.repository)
                                        let row = frm.add_child("custom")
                                        row.title = app.repository,
                                            row.app_name = app.name
                                    }
                                }
                            }
                        })
                        frm.refresh_field("custom")
                        frm.save()
                        frappe.ui.toolbar.clear_cache()
                        // frm.reload_doc()
                    } else {
                        frappe.throw("Add New app to update")
                    }
                } else {
                    frappe.throw("Add New App to update")
                }
            }, __("Updates"))
        }



        if (!frm.doc.__islocal && frm.doc.id && !frm.doc.is_dropped) {
            frm.add_custom_button("Remove App", function () {

                frappe.call({
                    doc: frm.doc,
                    method: "show_installed_apps",
                    args: {
                        "name": frm.doc.id
                    }, callback: function (r) {
                        let options = ""
                        // console.log(r.message.message)
                        for (let i of r.message.message) {
                            if (i.name != 'frappe') {
                                options += `\n${i.name}`
                            }
                        }
                        let d = new frappe.ui.Dialog({
                            title: "Remove App",
                            fields: [
                                {
                                    "fieldname": "app",
                                    "label": "App",
                                    "fieldtype": "Select",
                                    "options": options
                                }
                            ],
                            primary_action_label: "Remove App",
                            primary_action(values) {
                                frappe.confirm("Do You Want to Remove app?",
                                    () => {
                                        if (values.app) {
                                            frm.fields_dict.apps.df.hidden = 0
                                            frm.refresh_field("apps")


                                            // console.log(values.app)
                                            frappe.call({
                                                doc: frm.doc,
                                                method: "remove_app",
                                                async: false,
                                                args: {
                                                    "id": frm.doc.id,
                                                    "name": values.app
                                                }, callback: function (r) {
                                                    if (r.message) {
                                                        // console.log(JSON.parse(r.message._server_messages))
                                                        let err_data = JSON.parse(r.message._server_messages)
                                                        let err_message = JSON.parse(err_data[0]).message
                                                        frm.fields_dict.apps.df.hidden = 1
                                                        frm.refresh_field("apps")
                                                        frappe.throw(err_message)
                                                    } else {
                                                        frappe.msgprint("removed successfully")
                                                        let install_apps = frm.doc.apps
                                                        // console.log(install_apps)
                                                        for (let i of install_apps) {
                                                            // console.log(i.title)
                                                            // frm.set_value("apps")
                                                            if (i.title == values.app) {
                                                                // console.log(i.title)
                                                                // console.log(i.idx)
                                                                let idx = i.idx
                                                                frm.grids[0].grid.grid_rows[idx - 1].remove()
                                                                // console.log("removed")
                                                                let in_apps = []
                                                                frappe.call({
                                                                    doc: frm.doc,
                                                                    method: "get_installed_apps",
                                                                    args: {
                                                                        "title": frm.doc.id
                                                                    },
                                                                    async: false,
                                                                    callback: function (r) {

                                                                        frm.set_value("custom", "")
                                                                        var apps = r.message
                                                                        // console.log(apps)
                                                                        var capps = frm.doc.apps
                                                                        for (var a of capps) {
                                                                            // console.log(a.name1)
                                                                            in_apps.push(a.name1)
                                                                        }
                                                                        for (var app of apps) {
                                                                            // console.log("bench apps")
                                                                            // console.log(app)
                                                                            if (!in_apps.includes(app.name)) {
                                                                                // console.log(app.name)
                                                                                // console.log(app.repository)
                                                                                let row = frm.add_child("custom")
                                                                                row.title = app.repository,
                                                                                    row.app_name = app.name
                                                                            }
                                                                        }
                                                                    }
                                                                })
                                                                frm.refresh_field("custom")
                                                                frm.save()
                                                            }
                                                        }
                                                    }

                                                }
                                            })

                                            // setTimeout(function(){
                                            d.hide()

                                        } else {
                                            frappe.throw("Select Atleast One App To Uninstall")
                                        }
                                        // },10)
                                        // frm.fields_dict.apps.df.hidden = 1
                                        // frm.refresh_field("apps")
                                    })
                            },
                            secondary_action_label: "Update Later",
                            secondary_action() {
                                frm.fields_dict.apps.df.hidden = 1
                                frm.refresh_field("apps")
                                d.hide()
                            }
                        })
                        d.show()
                    }
                })
            }, __("Menu"))
        }



        if (!frm.doc.__islocal && frm.doc.id && !frm.doc.is_dropped) {
            frm.add_custom_button("Add From Github", function () {
                let name
                let id = frm.doc.id
                let status = frm.doc.status
                let fields = [], options = "", owner

                let d = new frappe.ui.Dialog({
                    title: "Add apps",
                    fields: [{
                        "fieldname": "owner",
                        "label": "Owner",
                        "fieldtype": "Data"
                    }, {
                        "fieldname": "repository",
                        "label": "Repository",
                        "fieldtype": "Select",
                        "onchange": function () {
                            // Is Available on github
                            let data = JSON.parse(frm.doc.repository_data)
                            for (var r of data.installations) {
                                for (var repo of r.repos) {
                                    if (d.fields_dict['repository'].value == repo.name) {
                                        d.fields_dict['repo_url'].value = repo.url
                                        d.fields_dict['branch'].value = repo.default_branch
                                    }
                                }
                            }
                            if (d.fields_dict['app_name'].value) {
                                d.fields_dict['app_name'].value = ""
                                d.fields_dict['app_title'].value = ""
                            }
                            d.refresh()
                            frappe.call({
                                doc: frm.doc,
                                method: "available_app",
                                args: {
                                    "id": data.installations[0].id,
                                    "name": d.fields_dict["repository"].value,
                                    "owner": data.installations[0].login,
                                },
                                async: true,
                                freeze: true,
                                freeze_message: "Checking Github",
                                callback: function (r) {
                                    // console.log("available app")
                                    // console.log(r.message)
                                    name = r.message.message.name
                                    // frappe.msgprint("Available App")
                                }
                            })
                        }
                    },
                    {
                        "fieldname": "repo_url",
                        "label": "Repository URL",
                        "fieldtype": "Data"
                    }, {
                        "fieldname": "branch",
                        "label": "Branch",
                        "fieldtype": "Data"
                    }, {
                        "fieldname": "validate",
                        "fieldtype": "Button",
                        // "value":"Validate",
                        "label": "Validate",
                        "description": "Click Button to Validate App"
                    }, {
                        "fieldname": "app_name",
                        "label": "App Name",
                        "fieldtype": "Data",
                        "reqd": 1,
                        "read_only": 1,
                        "description": "Validate and get app name"
                    }, {
                        "fieldname": "app_title",
                        "label": "App Title",
                        "fieldtype": "Data",
                        "reqd": 1,
                        "read_only": 1,
                        "description": "Validate and get app title"
                    }
                    ],
                    primary_action_label: "Submit",
                    primary_action(values) {
                        let data = JSON.parse(frm.doc.repository_data)
                        frappe.call({
                            doc: frm.doc,
                            method: "add_custom_app",
                            freeze: true,
                            freeze_message: "Adding App",
                            args: {
                                "branch": d.fields_dict['branch'].value,
                                "install_id": data.installations[0].id,
                                "bench": frm.doc.id,
                                "name": d.fields_dict['app_name'].value,
                                "url": d.fields_dict['repo_url'].value,
                                "title": d.fields_dict["app_title"].value
                            }
                        })
                        frm.save()
                        d.hide()
                    }
                })
                d.fields_dict["validate"].onclick = function () {
                    //Is Validated on Github
                    let data = JSON.parse(frm.doc.repository_data)
                    frappe.call({
                        doc: frm.doc,
                        method: "validate_app",
                        freeze: true,
                        freeze_message: "Validating Application",
                        args: {
                            "branch": d.fields_dict['branch'].value,
                            "install_id": data.installations[0].id,
                            "owner": data.installations[0].login,
                            "repo": d.fields_dict['repository'].value
                        },
                        callback: function (r) {
                            // console.log("validate app")
                            // console.log(r.message)
                            var res = r.message.message
                            var key = Object.keys(res)
                            // console.log(key)
                            if (key) {
                                for (var i of key) {
                                    if (i == "name") {
                                        if (res.name && res.title) {
                                            // console.log(res.name)
                                            // console.log(res.title)
                                            // console.log(app_name)
                                            // frm.set_value("app_name", res.name)
                                            // frm.set_value("app_title", res.title)
                                            d.fields_dict['app_name'].value = res.name
                                            d.fields_dict['app_title'].value = res.title
                                            d.refresh()
                                            frappe.msgprint("Validated")
                                        }
                                        else {
                                            frappe.throw("Custom App is not Valid")
                                        }
                                    }
                                }
                            }
                        }
                    })
                }
                frappe.call({
                    doc: frm.doc,
                    method: "get_git_repo",
                    async: true,
                    freeze: true,
                    freeze_message: "Validating Github",
                    callback: function (r) {
                        // console.log(r.message)
                        var repo_data = JSON.stringify(r.message.message)
                        // console.log(repo_data)
                        frm.set_value("repository_data", repo_data)
                        let data = JSON.parse(frm.doc.repository_data)
                        // let data = JSON.parse(repo_data)
                        owner = data.installations[0].login
                        for (var repos of data.installations[0].repos) {
                            // console.log(repos.name)
                            options += `\n${repos.name}`
                        }
                        // console.log(fields)

                        // console.log("owner" + owner)
                        // console.log("options" + options)
                        // d.fields_dict["bench_name"].value = name
                        // d.fields_dict["bench_id"].value = id
                        // d.fields_dict["bench_status"].value = status
                        d.fields_dict["owner"].value = owner
                        d.fields_dict["repository"].df.options = options
                        d.refresh()
                        d.show()
                    }
                })
                // console.log(fields)

                // console.log("owner"+owner)
                // console.log("options"+options)
                // d.fields_dict["bench_name"].value=name
                // d.fields_dict["bench_id"].value=id
                // d.fields_dict["bench_status"].value=status
                // d.fields_dict["owner"].value=owner
                // d.refresh()
                // d.show()
                // cur_dialog.fields_dict.bench_id.value=frm.doc.id
                // cur_dialog.refresh()
            }, __("Menu"))
        }



        if (!frm.doc.__islocal && frm.doc.id && !frm.doc.is_dropped) {
            frm.add_custom_button(("Drop Bench"), function () {
                frappe.confirm("Do You Want to Drop " + frm.doc.bench + " ?",
                    () => {
                        frappe.msgprint("")
                        frappe.call({
                            doc: frm.doc,
                            method: "drop_bench",
                            args: {
                                'title': frm.doc.id
                            },
                            callback: function (r) {
                                if (Object.keys(r.message) == 0) {
                                    frm.set_value("is_dropped", 1)
                                    frm.set_value("status", "Archived")
                                    frm.set_value("project", "")
                                    frm.save()
                                }
                            }
                        })
                    }
                )
            }, __("Menu"))
        }



        if (!frm.doc.__islocal && frm.doc.id && !frm.doc.is_dropped) {
            frm.add_custom_button("Update All Sites", function () {
                let available_version, primary_action_value = ""
                frappe.call({
                    doc: frm.doc,
                    method: "versions",
                    args: {
                        "id": frm.doc.id
                    },
                    async: false,
                    callback: function (r) {
                        // console.log(r.message.message)
                        available_version = r.message.message
                    }
                })
                // console.log("available version")
                // console.log(available_version)
                let fields = []
                for (let ver of available_version) {
                    let f = { "label": `${ver.name}` + " status:" + `${ver.status}` + " last_deployed:" + `${ver.deployed_on}`, 'fieldtype': "Check   ", "fieldname": `${ver.name}` + " " + `${ver.deployed_on}` }
                    fields.push(f)
                }
                // console.log(fields.length)
                if (fields.length > 1) {
                    let d = new frappe.ui.Dialog({
                        title: "Current Versions",
                        fields: fields,
                        primary_action_label: "Update All Site",
                        primary_action(values) {
                            // console.log(values)
                            frappe.call({
                                doc: frm.doc,
                                method: "update_site",
                                args: {
                                    "id": frm.doc.id
                                }, async: false,
                                callback: function (r) {
                                    // console.log(r.message)
                                }
                            })
                            d.hide()
                        }
                    })
                    d.show()
                } else {
                    frappe.msgprint("Currently One Bench Version Available")
                }
            }, __("Updates"))
        }



        if (!frm.doc.__islocal && frm.doc.id && !frm.doc.is_dropped) {
            frm.add_custom_button("Bench Build", function () {
                frappe.confirm("bench build command will be executed on your bench. This will regenerate all static assets. Are you sure you want to run this command?",
                    () => {
                        frappe.call({
                            doc: frm.doc,
                            method: "bench_build",
                            args: {
                                title: frm.doc.id
                            }, callback: function (r) {
                                if (Object.keys(r.message) == 0) {
                                    frappe.msgprint("Bench Build Successfull")
                                } else {
                                    frappe.throw("Error in Building Bench")
                                }
                                // console.log(r.message)
                            }
                        })
                    }
                )
            }, __("Menu"))
        }


        if (!frm.is_new()) {

            if (frm.doc.custom.length > 0) {
                frm.fields_dict.apps.df.hidden = 1
                frm.refresh_field("apps")
            }
            let data = JSON.parse(frm.doc.data)
            // console.log(r.message["message"])
            // console.log(data)
            // resData = JSON.stringify(r.message.message)
            // frm.set_value("data", resData)
            let benchOptions = ""
            for (var bench of data.versions) {
                // console.log(bench.name)
                benchOptions += '\n' + `${bench.name}`
            }
            frm.fields_dict.version.df.options = benchOptions
            frm.refresh_field('version')
            // }
            // }
            // })
            let clusterOptions = ""
            for (var r of data.versions) {
                // console.log(r)
                if (frm.doc.version == r.name) {
                    // console.log(r)
                    for (var cluster of data.clusters) {
                        // console.log(cluster)
                        clusterOptions += '\n' + `${cluster.name}`
                    }
                    frm.fields_dict.region.df.options = clusterOptions
                    frm.refresh_field('region')
                }
            }

        }

        frm.fields_dict["ssh_certificate"].set_label('SSH Certificate - <span class="fa fa-clipboard" style="font-size:18px" title="Copy to Clipboard"></span>');
        $(cur_frm.fields_dict['ssh_certificate'].label_area).on('click', function () {
            var fieldValue = frm.doc.ssh_certificate;

            // Create a temporary input element
            var tempInput = document.createElement("input");
            tempInput.value = fieldValue;
            document.body.appendChild(tempInput);

            // Select the input field contents
            tempInput.select();
            tempInput.setSelectionRange(0, 99999); // For mobile devices

            // Copy the selected text
            document.execCommand("copy");

            // Remove the temporary input element
            document.body.removeChild(tempInput);

            // Inform the user that the value has been copied
            frappe.show_alert('Value copied to clipboard!');
        })

        frm.fields_dict["command"].set_label('SSH Command - <span class="fa fa-clipboard" style="font-size:18px" title="Copy to Clipboard"></span>');
        $(cur_frm.fields_dict['command'].label_area).on('click', function () {
            var fieldValue = frm.doc.command;

            // Create a temporary input element
            var tempInput = document.createElement("input");
            tempInput.value = fieldValue;
            document.body.appendChild(tempInput);

            // Select the input field contents
            tempInput.select();
            tempInput.setSelectionRange(0, 99999); // For mobile devices

            // Copy the selected text
            document.execCommand("copy");

            // Remove the temporary input element
            document.body.removeChild(tempInput);

            // Inform the user that the value has been copied
            frappe.show_alert('Value copied to clipboard!');
        })

    }
    ,
    onload: function (frm) {
        if (frm.is_new()) {
            console.log("on load calling")
            frappe.call({
                doc: frm.doc,
                method: "get_bench_options",
                aysnc: false,
                callback: function (r) {
                    if (r.message) {
                        // console.log(r.message)
                        let data = r.message["message"]["versions"]
                        // console.log(r.message["message"])
                        // console.log(data)
                        let resData = JSON.stringify(r.message.message)
                        // console.log(resData)
                        frm.set_value("data", resData)
                        // console.log(frm.doc.data)
                        let benchOptions = ""
                        for (var bench of data) {
                            // console.log(bench.name)
                            benchOptions += '\n' + `${bench.name}`
                        }
                        frm.fields_dict.version.df.options = benchOptions
                        frm.refresh_field('version')
                    }
                }
            })
        }

    },
    // update_app: function (frm) {
    //     let session_roles = frappe.user_roles
    //     if (session_roles.some(item => ["Bench Add App", "Owner"])) {
    //         let apps = [], in_apps = []
    //         for (let i of frm.doc.apps) {
    //             apps.push(i.title)
    //         }
    //         const uniqueSet = new Set(apps);
    //         let set = Array.from(uniqueSet)
    //         if ((set.length) != (apps.length)) {
    //             frappe.throw("Delete duplicate apps")
    //         }
    //         let custom = []
    //         for (let app of frm.doc.custom) {
    //             // console.log(app.app_name)
    //             custom.push(app.app_name)
    //         }
    //         // console.log(custom)
    //         // console.log(custom.length)
    //         if (custom.length > 0) {
    //             let args = []
    //             for (let a of frm.doc.apps) {
    //                 if (!custom.includes(a.title)) {
    //                     // console.log(a.title)
    //                     // console.log(a.name1)
    //                     args.push({ "app": a.title, "source": a.name1 })
    //                 }
    //             }
    //             // console.log(args)
    //             // console.log(args.length)
    //             if (args.length > 0) {
    //                 frappe.call({
    //                     doc: frm.doc,
    //                     method: "update_app",
    //                     async: false,
    //                     args: {
    //                         "name": frm.doc.id,
    //                         "apps": args
    //                     }, callback: function (r) {
    //                         // console.log("callback update")
    //                     }
    //                 })
    //                 frm.set_df_property("update_app", "hidden", 1)
    //                 //get list of apps
    //                 frappe.call({
    //                     doc: frm.doc,
    //                     method: "get_installed_apps",
    //                     args: {
    //                         "title": frm.doc.id
    //                     },
    //                     async: false,
    //                     callback: function (r) {
    //                         frm.set_value("custom", "")
    //                         var apps = r.message
    //                         // console.log(apps)
    //                         var capps = frm.doc.apps
    //                         for (var a of capps) {
    //                             // console.log(a.name1)
    //                             in_apps.push(a.name1)
    //                         }
    //                         for (var app of apps) {
    //                             // console.log("bench apps")
    //                             // console.log(app)
    //                             if (!in_apps.includes(app.name)) {
    //                                 // console.log(app.name)
    //                                 // console.log(app.repository)
    //                                 let row = frm.add_child("custom")
    //                                 row.title = app.repository,
    //                                     row.app_name = app.name
    //                             }
    //                         }
    //                     }
    //                 })
    //                 frm.refresh_field("custom")
    //                 frm.save()
    //                 frappe.ui.toolbar.clear_cache()
    //                 // frm.reload_doc()
    //             } else {
    //                 frappe.throw("Add New app to update")
    //             }
    //         } else {
    //             frappe.throw("Add New App to update")
    //         }
    //     } else {
    //         frappe.throw("You don't have enough permissions to access this resource")
    //     }
    // },
    version: function (frm) {
        var jsonData = JSON.parse(frm.doc.data)
        let clusterOptions = ""
        // console.log(jsonData.versions)
        for (var data of jsonData.versions) {
            // console.log(data)
            if (frm.doc.version == data.name) {
                console.log(data)
                for (var cluster of jsonData.clusters) {
                    // console.log(cluster)
                    clusterOptions += '\n' + `${cluster.name}`
                }
                frm.fields_dict.region.df.options = clusterOptions
                frm.refresh_field('region')
            }
        }
    },
    // bench: function (frm) {
    // jsonData = JSON.parse(frm.doc.data)
    // for (var bench of jsonData.versions) {
    //     if (bench.title == frm.doc.bench) {
    //         // console.log(bench.name)
    //         frm.set_value("id", bench.name)
    //         frm.set_value("status", bench.status)
    //         frm.set_value("noof_apps", bench.number_of_apps)
    //         frm.set_value("version", bench.version)
    //         frm.call('get_dependencies')
    //             .then(r => {
    //                 // console.log(r.message.message)
    //                 var options = r.message.message.supported_dependencies
    //                 var versions = r.message.message.active_dependencies
    //                 bench_options = "", python_options = "", wkhtmltopdf_options = "", nvm_options = ""
    //                 for (var key of options) {
    //                     if (key.key === "BENCH_VERSION") {
    //                         bench_options += '\n' + `${key.value}`

    //                     }
    //                     if (key.key === "PYTHON_VERSION") {
    //                         python_options += '\n' + `${key.value}`

    //                     }
    //                     if (key.key === "WKHTMLTOPDF_VERSION") {
    //                         wkhtmltopdf_options += '\n' + `${key.value}`

    //                     }
    //                     if (key.key === "NVM_VERSION") {
    //                         nvm_options += '\n' + `${key.value}`

    //                     }
    //                 }
    //                 frm.fields_dict.bench_version.df.options = bench_options
    //                 frm.fields_dict.python_version.df.options = python_options
    //                 frm.fields_dict.wkhtmltopdf_version.df.options = wkhtmltopdf_options
    //                 frm.fields_dict.nvm_version.df.options = nvm_options

    //                 setTimeout(function () {
    //                     for (var each of versions) {
    //                         if (each.key === 'NVM_VERSION') { frm.set_value("nvm_version", each.value) }
    //                         if (each.key === 'BENCH_VERSION') { frm.set_value("bench_version", each.value) }
    //                         if (each.key === 'PYTHON_VERSION') { frm.set_value("python_version", each.value) }
    //                         if (each.key === 'NODE_VERSION') { frm.set_value("node_version", each.value) }
    //                         if (each.key === 'WKHTMLTOPDF_VERSION') { frm.set_value("wkhtmltopdf_version", each.value) }

    //                     }
    //                 }, 1500)
    //             })
    //         frm.call("get_apps")
    //             .then(r => {
    //                 console.log(r.message.message)
    //                 apps = r.message.message
    //                 var list = []
    //                 for (var app of apps) {
    //                     list.push(app.title)
    //                     var childRow = frm.add_child('apps', {
    //                         'title': app.title,

    //                     });
    //                 }
    //                 listStr = list.join(",")
    //                 frm.set_value("installed_apps", listStr)
    //                 frm.refresh_field('apps')

    //             })
    // frm.call("get_installable_apps")
    // .then(r=>{
    //     console.log(r.message.message)
    //     var apps = r.message.message
    //     app_options = ""
    //     for(var app of apps){
    //         console.log(app.title)
    //         var row = frm.add_child("apps");
    //         // frappe.model.set_value(row.doctype, row.name, "title", app.title);
    //         app_options += '\n'+`${app.title}`
    //     }
    //     frm.fields_dict.apps.df.options = app_options
    // })
    // }

    // }
    // },
    // update_dependencies: function (frm) {
    //     frm.call('update_dependencies')
    //         .then(r => {
    //             // console.log(r.message)
    //             frappe.msgprint({
    //                 title: __('Notification'),
    //                 indicator: 'green',
    //                 message: __('Version updated successfully')
    //             });
    //         })
    // }

});
// function create_build(frm) {
//     frm.add_custom_button("Bench Build", function () {
//         frappe.confirm("bench build command will be executed on your bench. This will regenerate all static assets. Are you sure you want to run this command?",
//             () => {
//                 frappe.call({
//                     doc: frm.doc,
//                     method: "bench_build",
//                     args: {
//                         title: frm.doc.id
//                     }, callback: function (r) {
//                         console.log(r.message)
//                     }
//                 })
//             }
//         )
//     }, __("Menu"))
// }
// function bench_jobs(frm) {
//     frappe.call({
//         doc: frm.doc,
//         method: "bench_jobs",
//         args: {
//             title: frm.doc.id
//         }, async: false,
//         callback: function (r) {
//             console.log(r.message)
//             let data = r.message.message
//             frm.set_value("jobs", "")
//             // frm.refresh_field("jobs")
//             for (let i of data) {
//                 console.log(i.job_type)
//                 var row = frm.add_child("jobs")
//                 row.title = i.job_type
//                 row.start = i.start
//                 row.end = i.end
//                 row.status = i.status
//             }
//             frm.refresh_field("jobs")

//         }
//     })
//     // frm.save()
// }

frappe.ui.form.on("Go1 FCloud Bench Site", {
    view_site: function (frm, cdt, cdn) {
        var d = locals[cdt][cdn]
        // console.log(d.sites)
        frappe.call({
            doc: frm.doc,
            method: "get_site_doc",
            async: false,
            args: {
                "url": d.sites
            },
            callback: function (r) {
                // console.log(r.message)
                window.open("/app/go1-fcloud-site/" + r.message, "_blank")
            }
        })
    }
})

frappe.ui.form.on("Go1 FCloud Bench Deploy",{
    
    form_render(frm,cdt,cdn){
        var d = locals[cdt][cdn]
        let wrapper = frm.fields_dict[d.parentfield].grid.grid_rows_by_docname[cdn].grid_form.fields_dict['step_html'].wrapper
        const steps = JSON.parse(d.steps)
        if(d.completed.includes("ago")){

        }
        let build_duration = (d.completed && d.duration)? (d.completed.includes("ago") && d.duration) ? `<h5 style="color:grey;">Completed ${d.completed} in ${d.duration}</h5>`:`<h5 style="color:grey;">Completed ${d.completed} days ago in ${d.duration}</h5>`:""
        $(`<h5>Build Log</h5> ${build_duration}`).appendTo(wrapper)
        var val = 0;
        for(let i of steps){
            if(!i.output){
                i.output = 'No Output!'
            }
            if(!i.command){
                i.command = "No Commmand !"
            }
            let symbol = i.status == "Success" ? '<i class="fa fa-check-circle" style="font-size:20px;color:#59ba8b;margin-right:7px;"></i>' : i.status == "Pending"?"<i class='fa fa-clock-o' style='font-size:20px;color:grey;margin-right:7px;'></i>":'<i class="fa fa-times-circle" style="font-size:20px;color:#ff0c0cb0;margin-right:7px;"></i>' 
            let color = i.status == "Success" ? "#59ba8b" : i.status == "Pending" ? "grey" : "#ff0c0cb0";
            // let html = `<div style="padding:10px;border:1px solid #8080801c;margin-bottom:10px;border-radius:5px"> ${symbol} <b>${i.name}</b><br><br> <span><b>Status:</b></span> ${i.status} <br> <p><br> <b>Command:</b> <br></p>
            //             <p style="border:1px solid #80808040;padding:8px;border-radius:7px;"><code>${i.command}</code></p> <p><br> <b>Output:</b> <br></p><p style="border:1px solid #80808040;padding:15px;border-radius:7px;"><code>${i.output}</code></p></div>`;

            let collapse_html = `
            <div class="card" style="margin-bottom:12px;">
                <div class="card-header" style ="border-bottom:0px" id="heading" >
                    <h5 class="mb-0">
                        <button class="btn btn-link" type="button" data-toggle="collapse" data-target="#collapse${val}" >
                        ${symbol} ${i.name}
                        </button>
                        <p style="display:inline-block;float:right;color:white;border-radius:5px;background-color:${color};
                            padding:5px;margin-top:6px;font-size:12px;">${i.status}</p><i class="fa fa-angle-up"></i>
                    </h5>
                    
                </div>
            
                <div id="collapse${val}" class="collapse" >
                    <div class="card-body">
                        <p><b>Command:</b><br></p>
                        <p style="border:1px solid #80808040;padding:8px;border-radius:7px;"><code>${i.command}</code></p>
                        <p><b>Output:</b> <br></p>
                        <p style="border:1px solid #80808040;padding:15px;border-radius:7px;"><code>${i.output}</code></p>
                    </div>
                </div>
            </div>`
            $(collapse_html).appendTo(wrapper)
            val+=1
        }

        $(document).on('show.bs.collapse', '.collapse', function () {
            $(this).prev('.card-header').find('.fa.fa-angle-up').removeClass('fa-angle-up').addClass('fa-angle-down');
        });
        
        $(document).on('hide.bs.collapse','.collapse',function(){
            $(this).prev('.card-header').find('.fa.fa-angle-down').removeClass('fa-angle-down').addClass('fa-angle-up');

        })
        
    }
})

frappe.ui.form.on("Go1 FCloud Bench Job",{
    form_render(frm,cdt,cdn){
        var d = locals[cdt][cdn]
        let wrapper = frm.fields_dict[d.parentfield].grid.grid_rows_by_docname[cdn].grid_form.fields_dict['step_html'].wrapper
        const steps = JSON.parse(d.steps)
        let dur = !d.duration ? "0s" :d.duration
        let build_duration = d.completed ? (d.completed.includes("ago")) ? `<h5 style="color:grey;">Completed ${d.completed} in ${dur}</h5>`:`<h5 style="color:grey;">Completed ${d.completed} days ago in ${dur}</h5>`:""
        $(`<h5>${d.title}</h5> ${build_duration}`).appendTo(wrapper)
        var val =0
        for(let i of steps){
            if(!i.output){
                i.output = 'No Output!'
            }
            let color = i.status == "Success" ? "#59ba8b" : i.status == "Pending" || i.status == "Skipped" ? "grey" : "#ff0c0cb0";
            let symbol = i.status == "Success" ? '<i class="fa fa-check-circle" style="font-size:20px;color:#59ba8b;margin-right:7px;"></i>' : i.status == "Skipped" || i.status == "Pending" ? '<i class="fa fa-minus-circle" style="font-size:20px;color:grey;margin-right:7px;"></i>' : '<i class="fa fa-times-circle" style="font-size:20px;color:#ff0c0cb0;margin-right:7px;"></i>' 
            // let html = `<div style="padding:10px;border:1px solid #8080801c;margin-bottom:10px;border-radius:5px"> ${symbol} <b>${i.name}</b><br><br> <span><b>Status:</b></span> ${i.status} <br><p><br> <b>Output:</b> <br></p><p style="border:1px solid #80808040;padding:15px;border-radius:7px;"><code>${i.output}</code></p></div>`;
            let collapse_html = `<div class="card" style="margin-bottom:12px;">
                <div class="card-header" style ="border-bottom:0px" id="heading${val}" >
                <h5 class="mb-0">
                    <button class="btn btn-link" type="button" data-toggle="collapse" data-target="#collapse${val}" >
                    ${symbol} ${i.name}
                    </button>
                    <p style="display:inline-block;float:right;color:white;border-radius:5px;background-color:${color};
                        padding:5px;margin-top:6px;font-size:12px;">${i.status}</p><i class="fa fa-angle-down"></i>
                </h5>
                </div>
            
                <div id="collapse${val}" class="collapse" >
                <div class="card-body">
                    <p><br> <b>Output:</b> <br></p>
                    <p style="border:1px solid #80808040;padding:15px;border-radius:7px;"><code>${i.output}</code></p>
                </div>
                </div>
            </div>`
            $(collapse_html).appendTo(wrapper)
            val+=1
        }
        $(document).on('show.bs.collapse', '.collapse', function () {
            $(this).prev('.card-header').find('.fa.fa-angle-down').removeClass('fa-angle-down').addClass('fa-angle-up');
        });
        
        $(document).on('hide.bs.collapse','.collapse',function(){
            $(this).prev('.card-header').find('.fa.fa-angle-up').removeClass('fa-angle-up').addClass('fa-angle-down');

        })        
    }
})

frappe.ui.form.on('Apps', {
    apps_add(frm, cdt, cdn) {
        // var install = frm.doc.apps
        // let apps = []
        // for (let i of install) {
        //     apps.push(i.title)
        // }
        // const uniqueSet = new Set(apps);
        // console.log(uniqueSet)
        var d = locals[cdt][cdn]
        var json = JSON.parse(frm.doc.data)
        let appsOptions = ""
        for (var data of json.versions) {
            if (frm.doc.version == data.name) {
                // console.log(data.apps)
                for (var app of data.apps) {
                    if (frm.doc.version == "Version 15") {
                        var version = "version-15"
                    }
                    // console.log(app.name)
                    for (var src of app.sources) {
                        if (src.branch != "develop" && src.branch != "Develop" && src.branch != (version + "-beta")) {
                            var split = (src.name).split("-")
                            appsOptions += '\n' + `${split[1]}`
                        }
                    }
                }

                cur_frm.grids[0].grid.grid_rows[d.idx - 1].columns.title.df.options = appsOptions
                frm.refresh_field('apps')

            }

        }
    },
    title: function (frm, cdt, cdn) {
        var d = locals[cdt][cdn]
        // console.log(d.title)
        // var title = d.title
        // var split = title.split("-")
        // console.log(split[1])
        // d.name1 = split[1]
        // frm.refresh_field('apps')
        var json = JSON.parse(frm.doc.data)
        for (var data of json.versions) {
            if (frm.doc.version == data.name) {
                for (var app of data.apps) {
                    if (frm.doc.version == "Version 15") {
                        var version = "version-15"
                    }
                    for (var src of app.sources) {
                        if (src.branch != "develop" && src.branch != "Develop" && src.branch != (version + "-beta")) {
                            var split = (src.name).split("-")
                            if (split.includes(d.title)) {
                                d.name1 = src.name
                            }
                        }
                    }
                }
            }
        }
        frm.refresh_field('apps')
    }
})

