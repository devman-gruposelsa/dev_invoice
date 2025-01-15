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


    def _create_invoice(self, product_pack_field):
        account_move_obj = self.env['account.move']
        account_move_line_obj = self.env['account.move.line']

        for task in self:
            # Validación de egreso_completo
            if task.egreso_completo:
                raise ValidationError(f"Este tránsito no se puede facturar porque está en 'Egreso Completo'. (Tarea: {task.name})")

            # Buscar productos asociados al campo específico
            products = self.env['product.product'].search([('product_tmpl_id.' + product_pack_field, '=', True)])
            if not products:
                raise ValidationError('No hay productos configurados con el paquete solicitado.')

            # Crear la factura
            invoice = account_move_obj.create({
                'partner_id': task.partner_id.id,
                'move_type': 'out_invoice',  # Factura de cliente
                'invoice_origin': task.name,
            })
            _logger.info(f"Factura creada con ID: {invoice.id} para la tarea {task.name} (ID: {task.id})")

            # Agregar líneas de factura
            for product in products:
                line = account_move_line_obj.create({
                    'move_id': invoice.id,
                    'product_id': product.id,
                    'quantity': 1,  # Ajusta según sea necesario
                    'price_unit': product.lst_price,
                    'name': product.name,
                    'account_id': product.categ_id.property_account_income_categ_id.id,
                    'task_id': task.id,  # Relación con la tarea
                })
                _logger.info(f"Línea de factura creada con ID: {line.id}, relacionada con la tarea {task.name} (ID: {task.id})")

            # Verificar si las líneas tienen el task_id asignado
            for line in invoice.invoice_line_ids:
                _logger.info(f"Línea de factura {line.id} asociada a la tarea {line.task_id.id if line.task_id else 'No asignada'}")

    def action_create_income_invoice(self):
        _logger.info("Generando facturas de ingreso...")
        self._create_invoice('income_invoice_pack')

    def action_create_outcome_invoice(self):
        _logger.info("Generando facturas de egreso...")
        self._create_invoice('outcome_invoice_pack')

    def action_create_storage_invoice(self):
        account_move_obj = self.env['account.move']
        account_move_line_obj = self.env['account.move.line']

        for task in self:
            # Validación de egreso_completo
            if task.egreso_completo:
                raise ValidationError(f"Este tránsito no se puede facturar porque está en 'Egreso Completo'. (Tarea: {task.name})")

            # Buscar productos con el paquete de facturación de almacenamiento
            products = self.env['product.product'].search([('stock_invoice_pack', '=', True)])
            if not products:
                raise ValidationError('No hay productos configurados para facturación de almacenamiento.')

            # Crear la factura (account.move)
            invoice = account_move_obj.create({
                'partner_id': task.partner_id.id,
                'move_type': 'out_invoice',
                'invoice_origin': task.name,
            })

            _logger.info(f"Factura creada con ID: {invoice.id} para la tarea {task.name} (ID: {task.id})")

            # Agregar líneas de factura y vincularlas a la tarea
            for product in products:
                account_move_line_obj.create({
                    'move_id': invoice.id,
                    'product_id': product.id,
                    'quantity': task.volumen_total_stock,  # Usa el volumen total del stock
                    'price_unit': product.lst_price,
                    'name': product.name,
                    'account_id': product.categ_id.property_account_income_categ_id.id,
                    'task_id': task.id,  # Relación directa con la tarea
                })

            _logger.info(f"Tareas relacionadas con la factura {invoice.id}: {invoice.task_id.ids}")


    def _cron_generate_storage_invoices(self):
        tasks = self.env['project.task'].search([('stage_id.transito_cerrado', '=', False)])
        grouped_invoices = {}  # Agrupar tareas por cliente

        for task in tasks:
            if task.egreso_completo:
                # Ignorar tareas con egreso_completo=True
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

            # Crear la factura agrupada
            invoice = account_move_obj.create({
                'partner_id': partner.id,
                'move_type': 'out_invoice',
                'invoice_origin': ', '.join([task.name for task in task_list]),
            })

            _logger.info(f"Factura agrupada creada con ID: {invoice.id} para el cliente {partner.name}")

            # Agregar líneas de factura
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
                        'task_id': task.id,  # Relación con la tarea
                    })

            _logger.info(f"Tareas relacionadas con la factura {invoice.id}: {invoice.task_id.ids}")

    def _create_single_task_invoice(self, task):
        account_move_obj = self.env['account.move']
        account_move_line_obj = self.env['account.move.line']

        # Validación de egreso_completo
        if task.egreso_completo:
            raise ValidationError(f"Este tránsito no se puede facturar porque está en 'Egreso Completo'. (Tarea: {task.name})")

        # Buscar productos con el paquete de facturación de almacenamiento
        products = self.env['product.product'].search([('stock_invoice_pack', '=', True)])
        if not products:
            raise ValidationError('No hay productos configurados para facturación de almacenamiento.')

        # Crear la factura
        invoice = account_move_obj.create({
            'partner_id': task.partner_id.id,
            'move_type': 'out_invoice',
            'invoice_origin': task.name,
        })

        _logger.info(f"Factura creada con ID: {invoice.id} para la tarea {task.name} (ID: {task.id})")

        # Agregar líneas de factura
        for product in products:
            account_move_line_obj.create({
                'move_id': invoice.id,
                'product_id': product.id,
                'quantity': task.volumen_total_stock,
                'price_unit': product.lst_price,
                'name': f"{task.name} - {product.name}",
                'account_id': product.categ_id.property_account_income_categ_id.id,
                'task_id': task.id,  # Relación directa con la tarea
            })

        _logger.info(f"Tareas relacionadas con la factura {invoice.id}: {invoice.task_id.ids}")

    
    
    def action_generate_monthly_invoices(self):
        grouped_invoices = {}
        invalid_tasks = []

        for task in self:
            if task.egreso_completo:
                invalid_tasks.append(task)
                continue

            partner = task.partner_id

            if partner.monthly_invoice:
                if partner.id not in grouped_invoices:
                    grouped_invoices[partner.id] = []
                grouped_invoices[partner.id].append(task)
            else:
                self._create_single_task_invoice(task)

        if invalid_tasks:
            task_names = ', '.join([task.name for task in invalid_tasks])
            raise ValidationError(f"Las siguientes tareas tienen 'Egreso Completo' en True: {task_names}")

        for partner_id, task_list in grouped_invoices.items():
            partner = self.env['res.partner'].browse(partner_id)
            account_move_obj = self.env['account.move']
            account_move_line_obj = self.env['account.move.line']

            invoice = account_move_obj.create({
                'partner_id': partner.id,
                'move_type': 'out_invoice',
                'invoice_origin': ', '.join([task.name for task in task_list]),
            })

            _logger.info(f"Factura agrupada creada con ID: {invoice.id} para el cliente {partner.name}")

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
                        'task_id': task.id,
                    })

            _logger.info(f"Tareas relacionadas con la factura {invoice.id}: {invoice.task_id.ids}")

        
