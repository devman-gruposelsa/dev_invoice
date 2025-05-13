from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def check_and_update_order_status(self):
        for order in self:
            if order.state == 'sale':  # Verificar si el estado es 'pedido de venta'
                all_tasks_completed = True
                if order.task_ids:
                    for task in order.task_ids:
                        # Verificar si hay stock disponible para el lote con el mismo nombre que la tarea
                        lot_stock_qty = self.env['stock.quant'].search([
                            ('lot_id.name', '=', task.name),
                            ('quantity', '>', 0)
                        ])
                        if lot_stock_qty:
                            all_tasks_completed = False
                            break
                    if all_tasks_completed:
                        for task in order.task_ids:
                            task.write({'full_transit': True})
                    else:
                        for task in order.task_ids:
                            task.write({'full_transit': False})
            elif order.state in ['cancel', 'draft']:  # Si el pedido es cancelado o eliminado
                for task in order.task_ids:
                    task.write({'full_transit': False})

    #@api.model
    def write(self, vals):
        res = super(SaleOrder, self).write(vals)
        self.check_and_update_order_status()
        return res

    def unlink(self):
        for order in self:
            if order.state in ['cancel', 'draft']:
                for task in order.task_ids:
                    task.write({'full_transit': False})
        return super(SaleOrder, self).unlink()
    
    def action_create_outcome_invoice(self):
        _logger.info("Generando facturas de egreso...")
        return self._create_invoice('outcome_invoice_pack')

    def _create_invoice(self, product_pack_field):
        account_move_obj = self.env['account.move']
        account_move_line_obj = self.env['account.move.line']

        for order in self:
            # Validación de egreso_completo en las tareas asociadas
            for task in order.task_ids:
                if task.egreso_completo:
                    raise ValidationError(f"Este tránsito no se puede facturar porque está en 'Egreso Completo'. (Tarea: {task.name})")

            # Buscar productos asociados al campo específico
            products = self.env['product.product'].search([('product_tmpl_id.' + product_pack_field, '=', True)])
            if not products:
                raise ValidationError('No hay productos configurados con el paquete solicitado.')

            # Crear la factura
            invoice = account_move_obj.create({
                'partner_id': order.partner_id.id,
                'move_type': 'out_invoice',  # Factura de cliente
                'invoice_origin': order.name,
            })
            _logger.info(f"Factura creada con ID: {invoice.id} para el pedido {order.name} (ID: {order.id})")

            # Agregar líneas de factura
            for product in products:
                if product.product_tmpl_id.one_line_invoice:
                    # Agrupar tareas en una sola línea de factura
                    task_names = '-'.join(order.task_ids.mapped('name'))
                    line_vals = {
                        'move_id': invoice.id,
                        'product_id': product.id,
                        'quantity': len(order.task_ids),  # Cantidad basada en el número de tareas
                        'price_unit': product.lst_price,
                        'name': f"{product.name} - {task_names}",
                        'account_id': product.categ_id.property_account_income_categ_id.id,
                        'sale_id': order.id,  # Relación con el pedido
                        'task_id': order.task_ids[0].id,  # Relación con una de las tareas
                    }
                    account_move_line_obj.create(line_vals)
                    _logger.info(f"Línea de factura creada para producto con one_line_invoice: {product.name} - {task_names}")
                else:
                    for task in order.task_ids:
                        line = account_move_line_obj.create({
                            'move_id': invoice.id,
                            'product_id': product.id,
                            'quantity': 1,  # Ajusta según sea necesario
                            'price_unit': product.lst_price,
                            'name': f"{product.name} - {task.name}",
                            'account_id': product.categ_id.property_account_income_categ_id.id,
                            'sale_id': order.id,  # Relación con el pedido
                            'task_id': task.id,  # Relación con la tarea
                        })
                        _logger.info(f"Línea de factura creada con ID: {line.id}, relacionada con el pedido {order.name} (ID: {order.id}) y tarea {task.name} (ID: {task.id})")
            
            try:
                invoice.button_update_prices_from_pricelist()
            except Exception as e:
                _logger.error(f"Error al actualizar precios para la factura {invoice.id}: {str(e)}")

            # Validar y agregar productos para tareas con full_transit
            full_transit_tasks = order.task_ids.filtered(lambda task: task.full_transit)
            if full_transit_tasks:
                product_full_transit = self.env['product.product'].search([('product_tmpl_id.product_full_transit', '=', True)], limit=1)
                if not product_full_transit:
                    raise ValidationError('No hay productos configurados con el campo product_full_transit en True.')

                task_names = '-'.join(full_transit_tasks.mapped('name'))
                invoice_line_vals = {
                    'move_id': invoice.id,
                    'product_id': product_full_transit.id,
                    'quantity': 1,
                    'price_unit': product_full_transit.lst_price,
                    'name': f"{product_full_transit.name} - {task_names}",
                    'account_id': product_full_transit.categ_id.property_account_income_categ_id.id,
                    'sale_id': order.id,  # Relación con el pedido
                    'task_id': full_transit_tasks[0].id,  # Relación con una de las tareas
                }
                account_move_line_obj.create(invoice_line_vals)
                _logger.info(f"Línea de factura creada para tareas con full_transit: {task_names}")

            # Devolver una acción para abrir la factura recién creada
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'view_mode': 'form',
                'res_id': invoice.id,
                'target': 'current',
            }
