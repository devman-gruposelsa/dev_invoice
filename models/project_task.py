# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ProjectTask(models.Model):
    _inherit = 'project.task'

    transit_total_cost = fields.Float(
        string='Costo total del transito',
        compute='_compute_transit_total_cost',
        store=True,
        help="Sum of the untaxed amounts of all filtered invoices associated with this task."
    )

    def costo_total_transito(self):
        for rec in self:
            rec._compute_transit_total_cost()

    #@api.depends('invoice_ids_filtered.amount_untaxed_signed')
    def _compute_transit_total_cost(self):
        for rec in self:
            # Inicializa una lista para almacenar facturas filtradas
            invoices_filtered = []
            
            # Busca todas las facturas (esto podría optimizarse si se conoce el rango necesario)
            invoices = self.env['account.move'].search([])
            _logger.info("Todas las facturas: %s", invoices.ids)

            # Filtra las facturas relacionadas con esta tarea
            for record in invoices:
                if record.task_id:
                    for task in record.task_id:
                        _logger.info("Factura: %s relacionada con tarea: %s", record.id, task.id)
                        if task.id == rec.id:
                            invoices_filtered.append(record)
            
            # Calcula el costo total de las facturas filtradas
            rec.transit_total_cost = sum(invoice.amount_untaxed_signed for invoice in invoices_filtered)

            # Registra la información para depuración
            _logger.info("Tarea: %s | Facturas filtradas: %s", rec.id, [inv.id for inv in invoices_filtered])
            _logger.info("Tarea: %s | Transit Total Cost: %s", rec.id, rec.transit_total_cost)


    def action_create_income_invoice(self):
        self._create_invoice('income_invoice_pack')

    def action_create_outcome_invoice(self):
        self._create_invoice('outcome_invoice_pack')

    def _create_invoice(self, product_pack_field):
        account_move_obj = self.env['account.move']
        account_move_line_obj = self.env['account.move.line']

        for task in self:
            # Buscar productos asociados al campo específico
            products = self.env['product.product'].search([('product_tmpl_id.' + product_pack_field, '=', True)])
            if not products:
                raise ValidationError('No hay productos configurados con el paquete solicitado.')

            # Crear la factura (account.move) y relacionarla con la tarea
            invoice = account_move_obj.create({
                'partner_id': task.partner_id.id,
                'move_type': 'out_invoice',  # Factura de cliente
                'invoice_origin': task.name,
                'task_id': [(4, task.id)],  # Relación Many2many con la tarea
                'invoice_line_ids': [],
            })

            # Agregar líneas de factura
            for product in products:
                account_move_line_obj.create({
                    'move_id': invoice.id,
                    'product_id': product.id,
                    'quantity': 1,  # Ajusta según sea necesario
                    'price_unit': product.lst_price,
                    'name': product.name,
                    'account_id': product.categ_id.property_account_income_categ_id.id,
                })

    def action_create_storage_invoice(self):
        account_move_obj = self.env['account.move']
        account_move_line_obj = self.env['account.move.line']

        for task in self:
            # Buscar productos con el paquete de facturación de almacenamiento
            products = self.env['product.product'].search([('stock_invoice_pack', '=', True)])
            if not products:
                raise ValidationError('No hay productos configurados para facturación de almacenamiento.')

            # Crear la factura (account.move) y relacionarla con la tarea
            invoice = account_move_obj.create({
                'partner_id': task.partner_id.id,
                'move_type': 'out_invoice',  # Factura de cliente
                'invoice_origin': task.name,
                'task_id': [(4, task.id)],  # Relación Many2many con la tarea
                'invoice_line_ids': [],
            })

            # Agregar líneas de factura con el volumen total del stock
            for product in products:
                account_move_line_obj.create({
                    'move_id': invoice.id,
                    'product_id': product.id,
                    'quantity': task.volumen_total_stock,
                    'price_unit': product.lst_price,
                    'name': product.name,
                    'account_id': product.categ_id.property_account_income_categ_id.id,
                })

    def _cron_generate_storage_invoices(self):
        tasks = self.env['project.task'].search([('stage_id.transito_cerrado', '=', False)])
        grouped_invoices = {}  # Almacena las tareas agrupadas por cliente

        for task in tasks:
            if task.egreso_completo:
                # Ignorar la tarea si tiene egreso_completo=True
                continue

            partner = task.partner_id

            if partner.monthly_invoice:
                if partner.id not in grouped_invoices:
                    grouped_invoices[partner.id] = []
                grouped_invoices[partner.id].append(task)
            else:
                # Crear factura individual por tarea
                self._create_single_task_invoice(task)

        # Crear facturas agrupadas por cliente
        for partner_id, task_list in grouped_invoices.items():
            partner = self.env['res.partner'].browse(partner_id)
            account_move_obj = self.env['account.move']
            account_move_line_obj = self.env['account.move.line']

            # Filtrar tareas con egreso_completo=True y continuar solo con las válidas
            valid_tasks = [task for task in task_list if not task.egreso_completo]
            if not valid_tasks:
                continue  # Si no hay tareas válidas, pasar al siguiente cliente

            # Crear la factura agrupada y asociarla a las tareas válidas
            invoice = account_move_obj.create({
                'partner_id': partner.id,
                'move_type': 'out_invoice',
                'invoice_origin': ', '.join([task.name for task in valid_tasks]),
                'task_id': [(4, task.id) for task in valid_tasks],  # Relación Many2many con tareas
                'invoice_line_ids': [],
            })

            # Agregar líneas de factura de cada tarea válida
            for task in valid_tasks:
                products = self.env['product.product'].search([('stock_invoice_pack', '=', True)])
                for product in products:
                    account_move_line_obj.create({
                        'move_id': invoice.id,
                        'product_id': product.id,
                        'quantity': task.volumen_total_stock,
                        'price_unit': product.lst_price,
                        'name': f"{task.name} - {product.name}",
                        'account_id': product.categ_id.property_account_income_categ_id.id,
                    })

    def _create_single_task_invoice(self, task):
        """Crear una factura individual para una tarea específica."""
        account_move_obj = self.env['account.move']
        account_move_line_obj = self.env['account.move.line']

        # Buscar productos con el paquete de facturación de almacenamiento
        products = self.env['product.product'].search([('stock_invoice_pack', '=', True)])
        if not products:
            raise ValidationError('No hay productos configurados para facturación de almacenamiento.')

        # Crear la factura y relacionarla con la tarea
        invoice = account_move_obj.create({
            'partner_id': task.partner_id.id,
            'move_type': 'out_invoice',
            'invoice_origin': task.name,
            'task_id': [(4, task.id)],  # Relación Many2many con la tarea
            'invoice_line_ids': [],
        })

        # Agregar líneas de factura
        for product in products:
            account_move_line_obj.create({
                'move_id': invoice.id,
                'product_id': product.id,
                'quantity': task.volumen_total_stock,
                'price_unit': product.lst_price,
                'name': f"{task.name} - {product.name}",
                'account_id': product.categ_id.property_account_income_categ_id.id,
            })
    
    
    def action_generate_monthly_invoices(self):
        grouped_invoices = {}  # Almacena las tareas agrupadas por cliente
        invalid_tasks = []  # Tareas con egreso_completo=True

        for task in self:
            if task.egreso_completo:
                # Agregar a la lista de tareas inválidas
                invalid_tasks.append(task)
                continue

            partner = task.partner_id

            if partner.monthly_invoice:
                if partner.id not in grouped_invoices:
                    grouped_invoices[partner.id] = []
                grouped_invoices[partner.id].append(task)
            else:
                # Crear factura individual por tarea
                self._create_single_task_invoice(task)

        # Levantar una alerta si hay tareas inválidas
        if invalid_tasks:
            task_names = ', '.join([task.name for task in invalid_tasks])
            raise ValidationError(f"Las siguientes tareas tienen 'Egreso Completo' en True y no se incluyeron: {task_names}")

        # Crear facturas agrupadas por cliente
        for partner_id, task_list in grouped_invoices.items():
            partner = self.env['res.partner'].browse(partner_id)
            account_move_obj = self.env['account.move']
            account_move_line_obj = self.env['account.move.line']

            # Crear la factura agrupada y asociarla a todas las tareas válidas
            invoice = account_move_obj.create({
                'partner_id': partner.id,
                'move_type': 'out_invoice',
                'invoice_origin': ', '.join([task.name for task in task_list]),
                'task_id': [(4, task.id) for task in task_list],  # Relación Many2many con tareas
                'invoice_line_ids': [],
            })

            # Agregar líneas de factura de cada tarea
            for task in task_list:
                products = self.env['product.product'].search([('stock_invoice_pack', '=', True)])
                for product in products:
                    account_move_line_obj.create({
                        'move_id': invoice.id,
                        'product_id': product.id,
                        'quantity': task.volumen_total_stock,
                        'price_unit': product.lst_price,
                        'name': f"{task.name} - {product.name}",
                        'account_id': product.categ_id.property_account_income_categ_id.id,
                    })

        
