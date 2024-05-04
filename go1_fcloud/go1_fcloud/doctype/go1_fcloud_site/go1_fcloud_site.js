// Copyright (c) 2024, Raino and contributors
// For license information, please see license.txt

frappe.ui.form.on("Go1 FCloud Site", {
    validate: function (frm) {
        if (frm.doc.site_name) {
            const special_character = /[!_@#$%^&*()\+={}[\]:;"'<>,.?\/|\\ ]/
            var is_special = special_character.test(frm.doc.site_name)
            if (is_special) {
                frappe.throw("site name should contain only letters,numbers and hyphens not any special characters")
            }
        } else {
            frappe.msgprint("Site Name is mandatory")
            validated = false
        }

        if (frm.doc.bench) {
            var avail = []
            var install = frm.doc.site
            var available = frm.doc.installed
            // console.log(available)
            for (let app of available) {
                avail.push(app.app_name)
            }
            for (var i of install) {
                if (!avail.includes(i.title)) {
                    frappe.throw(i.title + " is not available on " + frm.doc.bench)
                }
            }
        } else {
            //Validate Duplicate apps
            var install = frm.doc.site
            let apps = []
            for (let i of install) {
                apps.push(i.title)
            }
            const uniqueSet = new Set(apps);
            let set = Array.from(uniqueSet)
            if ((set.length) != (apps.length)) {
                frappe.throw("Delete duplicate apps")
            }
        }
        if (!frm.doc.url && !frm.doc.is_valid) {
            frappe.call({
                doc: frm.doc,
                method: "site_exists",
                args: {
                    "subdomain": frm.doc.site_name,
                    "domain": "frappe.cloud"
                }, callback(r) {
                    if (r.message) {
                        let value = r.message.message
                        if (value) {
                            frappe.msgprint(frm.doc.site_name + ".frappe.cloud already exists")
                            validated = false
                        } else {
                            frm.set_value("is_valid", 1)
                        }
                    }
                }
            })
        }


    },
    before_save: function (frm) {
        if (!frm.doc.__islocal || frm.doc.__islocal) {
            if (frm.doc.url) {
                if (frm.fields_dict.site.df.hidden == 0) {
                    // console.log("checking")
                    frm.fields_dict.custom.df.hidden = 0
                    frm.fields_dict.site.df.hidden = 1
                    frm.refresh_field("site")
                    frm.refresh_field("custom")
                }
            }
        }
        if (frm.doc.status == "Archived" && !frm.doc.is_dropped) {
            frm.set_value("is_dropped", 1)
            // frm.save()
        }

    },
    site_name: function (frm) {
        frappe.call({
            doc: frm.doc,
            method: "site_exists",
            args: {
                "subdomain": frm.doc.site_name,
                "domain": "frappe.cloud"
            }, callback(r) {
                // console.log(r.message)
                // console.log(r.message.message)
                if (r.message) {
                    if (r.message.message == true) {
                        // console.log("inside desc")
                        $('[class="help-box small text-muted"]').attr('style', "color:#e10000 !important")
                        frm.set_df_property("site_name", "description", frm.doc.site_name + ".frappe.cloud already exists")
                    } else {
                        $('[class="help-box small text-muted"]').attr('style', "color:#30a66d !important")
                        frm.set_df_property("site_name", "description", frm.doc.site_name + ".frappe.cloud is available")
                    }
                }
            }
        })
    },
    refresh: function (frm) {
        let session_roles = frappe.user_roles
        if (!frm.doc.__unsaved) {
            frm.set_df_property("site_name", "description", "")
        }
        if (frm.doc.version) {
            cur_frm.fields_dict.version.df.options = frm.doc.version
            cur_frm.fields_dict.region.df.options = frm.doc.region
            frm.refresh_field('version')
            frm.refresh_field('region')
        };
        //Set Plans after refresh
        let plans = ""
        // plans=""
        let plan = JSON.parse(frm.doc.plans)
        for (let p = 2; p < plan.length; p++) {
            // console.log(`\n${plan[p].name} - INR ${plan[p].price_inr}`)
            plans += `\n${plan[p].name} - INR ${plan[p].price_inr}`
        }
        frm.fields_dict.plan.df.options = plans
        frm.refresh_field("plan")
        if (!frm.doc.__islocal) {
            if (frm.doc.url) {
                frm.fields_dict.site.df.hidden = 1
            }
            let benchOptions = ""
            for (var bench of JSON.parse(frm.doc.bench_data)) {
                benchOptions += '\n' + `${bench.title}`
            }
            frm.fields_dict.bench.df.options = benchOptions
            frm.refresh_field('bench')
            frm.refresh_field('site')
        }

        if (!frm.doc.__islocal) {
            if (!frm.doc.url && !frm.doc.is_dropped) {
                let url
                frm.add_custom_button(('Create Site'), function () {
                    let value = frm.doc.plan.split('-')
                    let plan = value[0].trim()
                    frappe.call({
                        doc: frm.doc,
                        method: "create_site",
                        args: {
                            "group": frm.doc.group,
                            "bench": frm.doc.bench,
                            "apps": frm.doc.site,
                            "cluster": frm.doc.region,
                            "plan": plan,
                            "name": frm.doc.site_name
                        },
                        async: false,
                        callback: function (r) {
                            // console.log(r.message)
                            url = r.message.message.site
                        }
                    })
                    frm.set_value('url', url)
                    frm.refresh_field('url')
                    frm.save()
                })
            } else {
                if (!frm.doc.is_dropped) {
                    frm.add_custom_button("Get Status", function () {
                        var data
                        frappe.call({
                            doc: frm.doc,
                            method: "get_status",
                            args: {
                                "title": frm.doc.url,
                                "group": frm.doc.group,
                                "bench": frm.doc.bench
                            },
                            async: false,
                            callback: function (r) {
                                // console.log(r.message)
                                let data = r.message
                                frm.doc.custom = ""
                                for (var app of data[0].site_app) {
                                    // console.log(app.name)
                                    // console.log(app.repo)
                                    let row = frm.add_child("custom")
                                    row.title = app.name
                                    row.app_name = app.repo
                                }
                                frm.set_value("status", data[1].status)
                            }
                        });
                        // Get Installed apps - private bench
                        if (frm.doc.bench) {
                            let in_apps = []
                            frappe.call({
                                doc: frm.doc,
                                method: "get_installed_apps",
                                args: {
                                    "title": frm.doc.group
                                },
                                async: false,
                                callback: function (r) {
                                    frm.set_value("installed", "")
                                    var apps = r.message
                                    // console.log("site apps")
                                    // console.log(apps)
                                    for (let app of apps) {
                                        // console.log(app.name)
                                        let row = frm.add_child("installed")
                                        // // row.title = app.repository,
                                        row.app_name = app.name
                                    }
                                }
                            })
                        }
                        // frm.refresh_field("installed")
                        //Get site jobs
                        frappe.call({
                            doc: frm.doc,
                            method: "get_site_jobs",
                            args: {
                                "id": frm.doc.url
                            },
                            async: false,
                            callback: function (r) {
                                // console.log(r.message)
                                frm.set_value("jobs", "")
                                let data = r.message.message
                                for (let d of data) {
                                    frm.add_child("jobs", {
                                        "title": d.job_type,
                                        "creation1": d.creation,
                                        "status": d.status
                                    })
                                }
                            }
                        })
                        frm.save()
                        // frm.set_df_property("installed", "read_only", 1)
                    }, __("Options"))
                }
            }
        }



        if (!frm.doc.__islocal && !frm.doc.is_dropped && frm.doc.url) {
            frm.add_custom_button(__('Drop Site'), function () {
                frappe.confirm("Do you want to Drop the site", () => {
                    frappe.msgprint(__('Dropping site'));
                    frappe.call({
                        doc: frm.doc,
                        method: "drop_site",
                        aysnc: false,
                        callback: function (r) {
                            if (Object.keys(r.message) == 0) {
                                // frm.set_value("is_dropped", 1)
                                frm.set_value("status", "Archived")
                                frm.set_value("project", "")
                                frm.set_value("bench_name", "")
                                frm.save()
                            }
                        }
                    })
                })
            }, __("Options"));
        }



        if (!frm.doc.__islocal) {
            if (frm.doc.url && !frm.doc.is_dropped) {
                frm.add_custom_button("Restore Site", function () {
                    let options = ""
                    frappe.call({
                        doc: frm.doc,
                        method: "get_all_site",
                        async: false,
                        callback: function (r) {
                            let data = r.message.message
                            for (let d of data) {
                                if (frm.doc.url != d.name) {
                                    options += `\n${d.name}`
                                }
                            }
                        }
                    })
                    let d = new frappe.ui.Dialog({
                        title: "Restore Site",
                        fields: [
                            {
                                "label": "From Site URL",
                                "fieldname": "from_site",
                                "fieldtype": "Data",
                                "read_only": 1,

                            },
                            {
                                "label": "From Site Username",
                                "fieldname": "from_site_username",
                                "fieldtype": "Data",
                                "options": "email"
                            },
                            {
                                "label": "From Site Password",
                                "fieldname": "from_site_password",
                                "fieldtype": "Password"
                            },
                            {
                                "label": "Restore Site URL",
                                "fieldname": "restore_site",
                                "fieldtype": "Select",
                                "options": options,
                                "reqd": 1
                            }
                        ],
                        primary_action_label: "Restore",
                        primary_action(values) {
                            frappe.confirm("Do you want to Restore ?", () => {
                                // console.log(values)
                                // d.hide()
                                frappe.call({
                                    doc: frm.doc,
                                    method: "restore_site",
                                    args: {
                                        "from_site_url": values.from_site,
                                        "from_site_username": values.from_site_username,
                                        "password": values.from_site_password,
                                        "restore_site_url": values.restore_site
                                    },
                                    callback: function (r) {
                                        // console.log("restored")
                                        // console.log(r.message)
                                        if (r.message) {
                                            frappe.msgprint("Site Restored")
                                        }
                                    }
                                })
                                d.hide()
                            })
                        }
                    })
                    d.fields_dict["from_site"].value = frm.doc.url
                    d.refresh()
                    d.show()
                }, __("Options"))
            }
        }


        if (!frm.doc.__islocal) {
            if (frm.doc.url && !frm.doc.is_dropped) {
                frm.add_custom_button("Migrate", function () {
                    frappe.confirm("Do You want to Migrate the Site?",
                        () => {
                            frappe.call({
                                doc: frm.doc,
                                method: "migrate",
                                args: {
                                    "id": frm.doc.url
                                },
                                callback: function (r) {
                                    if (Object.keys(r.message) == 0) {
                                        frappe.msgprint("Site Migrated")
                                    }
                                }
                            })
                        })
                }, __("Options"))
            }
        }



        if (!frm.doc.__islocal) {
            if (frm.doc.url && !frm.doc.is_dropped) {
                frm.add_custom_button(__("Schedule Backup"), function () {
                    frappe.call({
                        doc: frm.doc,
                        method: "schedule_backup",
                        async: false,
                        callback: function (r) {
                            if (Object.keys(r.message) == 0) {
                                frappe.msgprint("Backup Scheduled.Click <b>Get Backup</b> to retrieve latest backup")
                            }
                        }
                    })
                }, __("Backup"));
                frm.add_custom_button(__('Get Backup'), function () {
                    // frappe.msgprint(__('Backup button clicked!'));
                    var db
                    frappe.call({
                        doc: frm.doc,
                        method: "backup_site",
                        aysnc: false,
                        callback: function (r) {
                            // console.log(r.message.message)
                            let db = r.message.message
                            // console.log(db)
                            // console.log(db.length)
                            // for(var d of db){
                            let db_url = db[0].database_url
                            let db_size = db[0].database_size
                            let db_file = db[0].database_file
                            let private_url = db[0].private_url
                            let private_file = db[0].private_file
                            let private_size = db[0].private_size
                            let public_url = db[0].public_url
                            let public_file = db[0].public_file
                            let public_size = db[0].public_size
                            // console.log(d.creation)
                            // console.log(d.database_url)
                            frm.set_value("database", db_url)
                            frm.set_value("private_url", private_url)
                            frm.set_value("public_url", public_url)
                            frm.set_value("database_file", db_file)
                            frm.set_value("public_file", public_file)
                            frm.set_value("private_file", private_file)
                            frm.set_value("database_size", db_size)
                            frm.set_value("public_size", public_size)
                            frm.set_value("private_size", private_size)
                            // }
                            frm.refresh_field('database')
                            frm.refresh_field('private_url')
                            frm.refresh_field('public_url')
                            frm.refresh_field('database_file')
                            frm.refresh_field('private_file')
                            frm.refresh_field('public_file')
                            frm.refresh_field('database_size')
                            frm.refresh_field('public_size')
                            frm.refresh_field('private_size')
                            frm.save()
                        }
                    })

                }, __("Backup"))
            }
        }



        if (!frm.doc.__islocal) {
            if (frm.doc.url && !frm.doc.is_dropped) {
                frm.add_custom_button("Login As Administrator", function () {
                    frappe.confirm("Admin login redirects to setup wizard, Do you want to be redirected ?", () => {
                        frappe.call({
                            doc: frm.doc,
                            method: "admin_login",
                            async: false,
                            callback: function (r) {
                                // console.log(r.message)
                                // console.log(r.message.message.sid)
                                // document.cookie="sid="+r.message.message.sid+";"
                                window.open("https://" + frm.doc.url + "/desk?sid=" + r.message.message.sid)
                            }
                        })
                    })
                }, __("Options"))
            }
        }



        if (!frm.doc.__islocal) {
            if (frm.doc.url && !frm.doc.is_dropped) {
                frm.add_custom_button("Activate", function () {
                    frappe.call({
                        doc: frm.doc,
                        method: "activate_site",
                        async: false,
                        callback: function (r) {
                            // console.log("activate response called...")
                            if (Object.keys(r.message) == 0) {
                                frappe.msgprint("Site Activated")
                            }

                        }
                    })
                }, __("Activation"))
                frm.add_custom_button("Deactivate", function () {
                    frappe.call({
                        doc: frm.doc,
                        method: "deactivate_site",
                        async: false,
                        callback: function (r) {
                            // console.log(r.message)
                            if (Object.keys(r.message) == 0) {
                                frappe.msgprint("Site Deactivated")
                            }
                        }
                    })
                }, __("Activation"))
            }
        }



        if (!frm.doc.__islocal) {
            if (frm.doc.url && !frm.doc.is_dropped) {
                // frm.add_custom_button("Update Apps", function () {

                // })
                frm.add_custom_button("Add App", function () {
                    let data
                    let custom = []
                    frappe.call({
                        doc: frm.doc,
                        method: "available_custom_apps",
                        args: {
                            "url": frm.doc.url
                        },
                        async: false,
                        callback: function (r) {
                            // console.log(r.message)
                            data = r.message.message
                            for (let c of data) {
                                // console.log(c.repository_owner)
                                custom.push({ "title": c.title, "repo": c.repository_owner, "branch": c.branch, "app": c.app })
                            }
                        }
                    })
                    let fields = []
                    if (custom.length > 0) {
                        for (var cust of custom) {
                            fields.push({
                                "label": `${cust.title}` + " (" + `${cust.repo}` + ":" + `${cust.branch}` + ")",
                                "fieldtype": "Check", "fieldname": `${cust.app}`
                            })
                        }
                        let d = new frappe.ui.Dialog({
                            title: "Available App (Install <b>One App</b> at a Time) ",
                            fields: fields,
                            primary_action_label: "Install",
                            primary_action(values) {
                                // console.log(values)
                                let in_app = []
                                for (let [key, v] of Object.entries(values)) {
                                    if (v == 1) {
                                        in_app.push({ "key": `${key}`, "value": `${v}` })
                                    }
                                }
                                // console.log(in_app[0].key)
                                if (in_app.length > 1) {
                                    frappe.throw("Install one app at a time")
                                } else {
                                    frappe.call({
                                        doc: frm.doc,
                                        method: "install_app_on_site",
                                        args: {
                                            "title": frm.doc.url,
                                            "app": in_app[0].key
                                        }, callback: function (r) {
                                            // console.log(r.message)
                                        }
                                    })
                                }
                                d.hide()

                                frm.set_intro("Click Get Status to get updated apps on site and bench")
                            }
                        })
                        d.show()
                    } else {
                        frappe.throw("Add Apps on Bench to Install")
                    }
                    // console.log(data)
                    // console.log(data.group)
                }, __("Options"))
            }
        }




        if (!frm.doc.__islocal) {
            if (frm.doc.url && !frm.doc.is_dropped) {
                frm.add_custom_button("Remove App", function () {
                    let options = ""
                    let apps = frm.doc.custom
                    // console.log(apps)
                    for (let a of apps) {
                        options += `\n${a.title}`
                    }
                    let d = new frappe.ui.Dialog({
                        title: "Remove Apps",
                        fields: [{
                            "label": "App",
                            "fieldname": "app",
                            "fieldtype": "Select",
                            "options": options
                        }],
                        primary_action_label: "Remove",
                        primary_action(values) {
                            frappe.confirm("All doctypes and modules pertaining to this app will be removed.",
                                () => {
                                    // console.log(values.app)
                                    frappe.call({
                                        doc: frm.doc,
                                        method: "remove_app",
                                        args: {
                                            "app": values.app,
                                            "name": frm.doc.url
                                        },
                                        async: false,
                                        callback: function (r) {

                                        }
                                    })
                                    d.hide()
                                    frm.set_intro("Click Get Status to get updated apps on site and bench")

                                },
                                () => {
                                    frm.reload_doc()
                                })
                        }
                    })
                    d.show()
                }, __('Options'))
            }
        }

    },
    onload: function (frm) {
        if (frm.is_new()) {
            if (!frm.doc.bench) {

                frappe.call({
                    doc: frm.doc,
                    method: "get_new_site_options",
                    async: false,
                    callback: function (r) {
                        // console.log(r.message)
                        let value = JSON.stringify(r.message)
                        frm.set_value("new_apps", value)
                        // frm.refresh_field("new_apps")
                    }
                })
            }
            frm.call({
                doc: frm.doc,
                method: 'get_options_for_site',
                async: false,
                callback: function (r) {
                    if (r.message) {
                        // console.log(r.message.message)
                        var versions = r.message['message']["versions"]
                        // console.log(versions)
                        let resData = JSON.stringify(r.message.message)
                        // console.log("res data")
                        // console.log(resData)
                        frm.set_value("site_data", resData)
                        let versionOptions = ""
                        for (var version of versions) {
                            // console.log(version)
                            versionOptions += '\n' + `${version.name}`
                        }
                        frm.fields_dict.version.df.options = versionOptions
                        frm.refresh_field('version')
                    }
                }
            })
            //Get Site Plans
            frappe.call({
                doc: frm.doc,
                method: 'get_site_plans',
                async: false,
                callback: function (r) {
                    if (r.message) {
                        let data = JSON.stringify(r.message.message)
                        frm.set_value("plans", data)
                        let plans = ""
                        // console.log("Getting plans")
                        // console.log(JSON.parse(frm.doc.plans).length)
                        let plan = JSON.parse(frm.doc.plans)
                        for (let p = 2; p < JSON.parse(frm.doc.plans).length; p++) {
                            // console.log(plan[p].name)
                            plans += `\n${plan[p].name}`
                        }
                        frm.fields_dict.plan.df.options = plans
                        frm.refresh_field("plan")
                    }
                }
            })
            //Bench Options
            frappe.call({
                doc: frm.doc,
                method: "get_bench_list",
                aysnc: false,
                callback: function (r) {
                    if (r.message) {
                        // console.log(r.message.message)
                        let data = r.message['message']
                        let resData = JSON.stringify(data)
                        frm.set_value("bench_data", resData)
                        let benchOptions = ""
                        for (var bench of JSON.parse(frm.doc.bench_data)) {
                            benchOptions += '\n' + `${bench.title}`
                            // console.log(bench.title)
                        }
                        frm.fields_dict.bench.df.options = benchOptions
                        frm.refresh_field('bench')

                    }
                }
            })
            if (frm.doc.bench) {
                // console.log("Bench avaialble on load" + frm.doc.bench)
                // console.log(frm.doc.data)
                frappe.call({
                    doc: frm.doc,
                    method: "get_bench_list",
                    async: false,
                    callback: function (r) {
                        if (r.message) {
                            // console.log(r.message.message)
                            let data = r.message['message']
                            let resData = JSON.stringify(data)
                            frm.set_value("bench_data", resData)
                            let benchOptions = ""
                            for (var bench of JSON.parse(frm.doc.bench_data)) {
                                benchOptions += '\n' + `${bench.title}`
                                // console.log(bench.title)
                            }
                            frm.fields_dict.bench.df.options = benchOptions
                            frm.refresh_field('bench')

                        }
                    }
                })
                let jsonData = JSON.parse(frm.doc.bench_data)
                // console.log(jsonData)
                for (var bench of jsonData) {
                    if (bench.title == frm.doc.bench) {
                        // console.log(bench.name)
                        frm.set_value("group", bench.name)
                        frm.set_value("bench_status", bench.status)
                    }
                }
            }

            // //Bench id and status
            // jsonData = JSON.parse(frm.doc.bench_data)
            // // console.log(jsonData)
            // for (var bench of jsonData) {
            //     if (bench.title == frm.doc.bench) {
            //         console.log(bench.name)
            //         frm.set_value("group", bench.name)
            //         frm.set_value("bench_status", bench.status)
            //     }
            // }

            // //Bench apps
            // if (frm.doc.installed) {
            //     frm.set_value("installed", "")
            //     frappe.call({
            //         doc: frm.doc,
            //         method: "get_apps",
            //         args: {
            //             "name": frm.doc.group
            //         },
            //         callback: function (r) {
            //             console.log(r.message)
            //             var apps = r.message.message
            //             for (var app of apps) {
            //                 frm.add_child("installed", {
            //                     "app_name": app.name
            //                 })
            //                 console.log(app.repository)
            //                 frm.refresh_field("installed")
            //             }
            //         }
            //     })
            // }
        }
    },
    bench: function (frm) {
        if (!frm.doc.bench) {
            frm.set_value("group", "")
            frm.set_value("bench_status", "")
            frm.set_value("installed", "")
        } else {
            let jsonData = JSON.parse(frm.doc.bench_data)
            // console.log(jsonData)
            for (var bench of jsonData) {
                if (bench.title == frm.doc.bench) {
                    // console.log(bench.name)
                    frm.set_value("group", bench.name)
                    frm.set_value("bench_status", bench.status)
                }
            }

        }
        // frm.refresh_field('group')
    },
    version: function (frm) {
        var jsonData = JSON.parse(frm.doc.site_data)
        if (!frm.doc.bench) {
            for (let i of jsonData.versions) {
                if (i.name == frm.doc.version) {
                    frm.set_value("group", i.group.name)
                }
            }
        }

        // var clusters = jsonData.versions[2].group.clusters
        // console.log(jsonData.versions[2].group.clusters)
        let clusterOptions = ""
        for (var data of jsonData.versions) {
            if (frm.doc.version == data.name) {
                // frm.set_value("group",data.group.name)
                // console.log(data)
                for (var cluster of data.group.clusters) {
                    // console.log(cluster)
                    clusterOptions += '\n' + `${cluster.name}`
                }
                frm.fields_dict.region.df.options = clusterOptions
                frm.refresh_field('region')
            }


        }
        frappe.call({
            doc: frm.doc,
            method: "get_bench_list",
            async: false,
            callback: function (r) {
                if (r.message) {
                    // console.log("bench list called...")
                    // console.log(r.message.message)
                    let data = r.message['message']
                    let resData = JSON.stringify(data)
                    frm.set_value("bench_data", resData)
                    let benchOptions = ""
                    for (var bench of JSON.parse(frm.doc.bench_data)) {
                        benchOptions += '\n' + `${bench.title}`
                        // console.log(bench.title)
                    }
                    frm.fields_dict.bench.df.options = benchOptions
                    frm.refresh_field('bench')

                }
            }
        })
    },

    // create_site: function(frm) {
    //     var args = {
    //         "group": frm.doc.group,
    //         // "apps": app_params,
    //         "cluster": frm.doc.region,
    //         "plan": frm.doc.plan,
    //         "name": frm.doc.site_name

    //     };

    //     // frm.call('create_site',args)
    //     //     .then(r => {
    //     //         console.log(r.message);

    //     //     });
    //     frm.call({
    //         doc:frm.doc,
    //         method:'create_site',
    //         args:args,
    //         callback:function(r){
    //             console.log("message from create site")
    //             console.log(r.message)
    //         }

    //     })
    // },

    //commented by jaffar
    // create_site: function(frm) {
    //     frm.call('get_token')
    //         .then(r => {
    //             // console.log(r.message);

    //             var app_params = frm.doc.apps.map(app => app.title);
    //             console.log(app_params)
    //             // for (var app of app_params) {
    //             //     console.log(app);
    //             // }

    //             var data = {
    //                 'site': {
    //                     "name": frm.doc.site_name,
    //                     "apps": app_params,
    //                     "group": frm.doc.group,
    //                     "cluster": frm.doc.region,
    //                     "plan": frm.doc.plan
    //                 }
    //             };
    //             console.log(data)
    //             var auth=r.message
    //             console.log("auth")
    //             console.log(auth)
    //             // fetch("https://frappecloud.com/api/method/press.api.site.new", {
    //             //     method: "POST",
    //             //     headers: {
    //             //         "Content-Type": "application/json",
    //             //         "Authorization": r.message[0],
    //             //         "X-Press-Team": r.message[1]
    //             //     },
    //             //     body: JSON.stringify(data),
    //             // }).then(response => {
    //             //     console.log(response.json())
    //             // })

    //         });
    // },
    group: function (frm) {
        if (frm.doc.bench) {
            // if (frm.doc.installed) {
            frm.set_value("installed", "")
            frappe.call({
                doc: frm.doc,
                method: "get_apps",
                args: {
                    "name": frm.doc.group
                },
                callback: function (r) {
                    // console.log(r.message)
                    var apps = r.message.message
                    for (var app of apps) {
                        frm.add_child("installed", {
                            "app_name": app.name
                        })
                        // console.log(app.repository)
                        frm.refresh_field("installed")
                    }
                }
            })
            // }
        }
    }
});
var default_apps = []
frappe.ui.form.on('Apps', {
    site_add(frm, cdt, cdn) {
        var d = locals[cdt][cdn]
        if (frm.doc.bench) {
            // console.log("apps")
            let appsOptions
            let options = []
            for (let i of frm.doc.installed) {
                if (i.app_name != "frappe") {
                    options.push(i.app_name)
                }
            }
            let rows = frm.doc.site //apps table
            // console.log(rows.length)
            if (rows.length > 1) {
                // console.log("greater than 1 runs")
                // console.log(rows.length)
                let updated = options
                for (let i = 0; i < rows.length - 1; i++) {
                    // console.log("rows title")
                    // console.log(rows[i].title)
                    let app = rows[i].title
                    let idx = updated.indexOf(app)
                    updated.splice(idx, 1)
                }
                cur_frm.grids[1].grid.grid_rows[d.idx - 1].columns.title.df.options = updated
            } else {
                // console.log("else runs")
                var d = locals[cdt][cdn]
                // var json = JSON.parse(frm.doc.data)
                // console.log(frm.doc.installed)
                // console.log(options)
                let appsOptions = ""
                for (let data of options) {
                    appsOptions += '\n' + `${data}`
                    // console.log(split)
                    cur_frm.grids[1].grid.grid_rows[d.idx - 1].columns.title.df.options = appsOptions
                    frm.refresh_field('apps')
                }
            }
        } else {
            let site_apps = ""
            let new_site_apps = JSON.parse(frm.doc.new_apps)
            for (let i of new_site_apps.versions) {
                if (frm.doc.version == i.name) {
                    let apps = i.group.apps
                    for (let app of apps) {
                        if (app.repository != 'frappe') {
                            site_apps += `\n${app.repository}`
                        }
                    }
                }
            }
            cur_frm.grids[1].grid.grid_rows[d.idx - 1].columns.title.df.options = site_apps
            frm.refresh_field('apps')
            // console.log(new_site_apps.versions)
        }
    },
    // title(frm, cdt, cdn) {
    //     var d = locals[cdt][cdn]
    //     // console.log(d.title)
    //     var title = d.title
    //     var split = title.split("-")
    //     // console.log(split[1])
    //     d.name1 = split[1]
    //     frm.refresh_field('apps')
    // }
})
// function update_site_app() {
//     frappe.call({
//         doc: cur_frm.doc,
//         method: "get_status",
//         args: {
//             "title": cur_frm.doc.url,
//             "group": cur_frm.doc.group
//         },
//         async: false,
//         callback: function (r) {
//             console.log(r.message)
//             data = r.message
//             cur_frm.doc.custom = ""
//             for (var app of data[0].site_app) {
//                 console.log(app.name)
//                 console.log(app.repo)
//                 let row = cur_frm.add_child("custom")
//                 row.title = app.name
//                 row.app_name = app.repo
//             }
//             cur_frm.set_value("status", data[1].status)
//             cur_frm.save()
//         }
//     })
// }

function get_status(frm) {
    frm.add_custom_button("Get Status", function () {
        var data
        frappe.call({
            doc: frm.doc,
            method: "get_status",
            args: {
                "title": frm.doc.url,
                "group": frm.doc.group
            },
            async: false,
            callback: function (r) {
                // console.log(r.message)
                let data = r.message
                frm.doc.custom = ""
                frm.doc.installed = ""
                for (var app of data[0].site_app) {
                    // console.log(app.name)
                    // console.log(app.repo)
                    let row = frm.add_child("custom")
                    row.title = app.name
                    row.app_name = app.repo
                }
                for (let s_app of data[0].bench_app) {
                    let row = frm.add_child("installed")
                    // row.title = app.repository,
                    row.app_name = s_app.name
                }
                frm.set_value("status", data[1].status)
                // frm.save()
            }
        });
        frm.save()
    }, __("Options"))
}