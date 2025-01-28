# -*- coding: utf-8 -*-
{
    'name': 'Dev_invoice',
    'version': '',
    'summary': """ Dev_invoice Summary """,
    'author': '',
    'website': '',
    'category': '',
    'depends': ['base', 'product', 'sale', 'project', 'import_folder_016', 'dev_insurances', 'dev_stock', 'exe_selsa_commission', 'account_invoice_pricelist'],
    "data": [
        "views/project_task_views.xml",
        "views/product_template_views.xml",
        "views/res_partner_views.xml",
        "views/sale_order_views.xml",
        "data/ir_action_data.xml",
        "data/project_task_data.xml"
    ],
    'application': True,
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
