# -*- coding: utf-8 -*-
{
    'name': 'Dev_invoice',
    'version': '16.10.5',
    'summary': """ Dev_invoice Summary """,
    'author': '',
    'website': '',
    'category': '',
    'depends': ['base', 'product', 'sale', 'project', 'import_folder_016', 'dev_insurances', 'dev_stock', 'exe_selsa_commission', 'account_invoice_pricelist', 'decimal_precision'],
    "data": [
        "security/ir.model.access.csv",
        "views/project_task_views.xml",
        "views/product_template_views.xml",
        "views/res_partner_views.xml",
        "views/sale_order_views.xml",
        "views/account_move_line_views.xml",
        "views/partner_product_special_minimum_views.xml", # New view file
        "wizards/project_task_days_invoiced_wizard.xml",
        "wizards/project_task_fecha_ingreso_wizard.xml",
        "wizards/update_task_relations_wizard_view.xml",
        "data/ir_action_data.xml",
        "data/project_task_data.xml",
        "data/ir_cron.xml"
    ],
    'application': True,
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
    
}
