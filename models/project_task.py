# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ProjectTask(models.Model):
    _inherit = 'project.task'

    transit_total_cost = fields.Float(
        string='Total Transit Cost',
        compute='_compute_transit_total_cost',
        store=True,
        help="Sum of the untaxed amounts of all filtered invoices associated with this task."
    )

    @api.onchange('purchase_order_ids.task_id', 'invoice_ids_filtered.amount_untaxed_signed')
    def _compute_transit_total_cost(self):
        for rec in self:
            invoices_filtered = []
            invoices= self.env['account.move'].search([])
            for record in invoices:
                if record.task_id:
                    for task in record.task_id:
                        _logger.info("record.task_id %s", task)
                        if task.id == rec.id:
                            invoices_filtered.append(record.id)
            rec.transit_total_cost = sum(invoices_filtered.amount_untaxed_signed)
            _logger.info("invoices_filtered %s", invoices_filtered)


    def action_create_income_invoice(self):
        self._create_sale_order('income_invoice_pack')

    def action_create_outcome_invoice(self):
        self._create_sale_order('outcome_invoice_pack')

    def _create_sale_order(self, product_pack_field):
        sale_order_obj = self.env['sale.order']
        sale_order_line_obj = self.env['sale.order.line']
        
        for task in self:
            products = self.env['product.product'].search([('product_tmpl_id.' + product_pack_field, '=', True)])
            if not products:
                raise ValidationError('No hay productos configurados con el paquete solicitado.')

            sale_order = sale_order_obj.create({
                'partner_id': task.partner_id.id,
                'task_ids': [(4, task.id)],
            })

            for product in products:
                sale_order_line_obj.create({
                    'order_id': sale_order.id,
                    'product_id': product.id,
                    'product_uom_qty': 1,  # Ajusta según necesidad
                })

    def action_create_storage_invoice(self):
        sale_order_obj = self.env['sale.order']
        sale_order_line_obj = self.env['sale.order.line']

        for task in self:
            products = self.env['product.product'].search([('stock_invoice_pack', '=', True)])
            if not products:
                raise ValidationError('No hay productos configurados para facturación de almacenamiento.')

            sale_order = sale_order_obj.create({
                'partner_id': task.partner_id.id,
                'task_ids': [(4, task.id)],
            })

            for product in products:
                sale_order_line_obj.create({
                    'order_id': sale_order.id,
                    'product_id': product.id,
                    'product_uom_qty': task.volumen_total_stock,
                })

    def _cron_generate_storage_invoices(self):
        
        tasks = self.env['project.task'].search([('stage_id.transito_cerrado', '=', False)])

        for task in tasks:
            task.action_create_storage_invoice()
        
