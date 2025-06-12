# -*- coding: utf-8 -*-
from odoo import models, fields, api

import logging
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

class AccountMoveInherit(models.Model):
    _inherit = 'account.move'

    task_id = fields.Many2many('project.task', 
                             string='Carpeta de importación', 
                             compute='_compute_task_id',
                             store=True,
                             copy=False)  # Evitar copiar al duplicar facturas

    @api.depends('invoice_line_ids.task_id', 'invoice_line_ids.sale_id.task_ids', 'move_type')
    def _compute_task_id(self):
        """Compute task_id field efficiently by minimizing database queries"""
        # Pre-fetch related records to avoid N+1 queries
        self.mapped('invoice_line_ids.task_id')
        self.mapped('invoice_line_ids.sale_id.task_ids')
        
        # Process only relevant invoices in bulk
        for rec in self:
            if rec.move_type not in ['out_invoice', 'out_refund']:
                rec.task_id = [(5, 0, 0)]
                continue
                
            # Get all task_ids in a single pass
            task_ids = set()
            sales_to_check = set()
            
            for line in rec.invoice_line_ids:
                if line.task_id and line.task_id.project_id.importation:
                    task_ids.add(line.task_id.id)
                elif line.sale_id:
                    sales_to_check.add(line.sale_id.id)
            
            # If we have sales orders, get their tasks efficiently
            if sales_to_check:
                sale_tasks = self.env['sale.order'].browse(list(sales_to_check)).mapped('task_ids').filtered(
                    lambda t: t.project_id.importation
                )
                task_ids.update(sale_tasks.ids)
            
            # Update tasks in one operation
            rec.task_id = [(6, 0, list(task_ids))]
        
        # Limpiar relaciones para otros tipos de movimientos
        for rec in self.filtered(lambda m: m.move_type not in ['out_invoice', 'out_refund']):
            rec.task_id = [(5, 0, 0)]

    @api.model
    def create(self, vals):
        record = super(AccountMoveInherit, self).create(vals)
        # record._update_task_relations() # Removed
        return record

    def write(self, vals):
        res = super(AccountMoveInherit, self).write(vals)
        # if 'invoice_line_ids' in vals: # Removed
            # self._update_task_relations() # Removed
        return res

    # def _update_task_relations(self): # Entire method removed
    #     """
    #     Actualiza las relaciones de tareas solo cuando es necesario
    #     """
    #     for rec in self:
    #         task_ids = []
    #         _logger.info(f"Actualizando relaciones de tareas para factura {rec.id}")
    #         for line in rec.invoice_line_ids:
    #             if line.task_id and line.task_id.project_id.importation:
    #                 task_ids.append(line.task_id.id)
    #                 _logger.info(f"Línea {line.id} asociada a la tarea {line.task_id.id}")
    #             elif line.sale_id and line.sale_id.task_ids:
    #                 for task in line.sale_id.task_ids:
    #                     if task.project_id.importation:
    #                         task_ids.append(task.id)
    #                         _logger.info(f"Orden de venta {line.sale_id.id} asociada a la tarea {task.id}")
            
    #         if set(task_ids) != set(rec.task_id.ids):
    #             rec.task_id = [(6, 0, task_ids)]
    #             _logger.info(f"Tareas actualizadas para factura {rec.id}: {task_ids}")

    def post(self):
        res = super(AccountMoveInherit, self).post()
        for rec in self:
            if rec.invoice_origin and 'Storage' in rec.invoice_origin.lower():
                if rec.invoice_date:
                    _logger.info(f"Procesando cálculo de próxima fecha de facturación para factura {rec.id}")
                    for task in rec.task_id:
                        # Calcular la fecha 30 días después de la fecha de la factura
                        next_billing_date = rec.invoice_date + timedelta(days=30)
                        task.date_next_billing = next_billing_date
                        _logger.info(f"Actualizada la próxima fecha de facturación para la tarea {task.id}: {next_billing_date}")
                else:
                    _logger.warning(f"La factura {rec.id} no tiene una fecha de factura válida.")
        return res

    def unlink(self):
        for rec in self:
            if rec.invoice_origin and 'storage' in rec.invoice_origin.lower():
                _logger.info(f"Eliminando la fecha de próxima facturación para las tareas asociadas a la factura {rec.id}")
                for task in rec.task_id:
                    task.date_next_billing = False
                    _logger.info(f"Fecha de próxima facturación eliminada para la tarea {task.id}")
        res = super(AccountMoveInherit, self).unlink()

        return res

    @api.model
    def _cron_update_task_relations(self):
        """
        Método para ser llamado por el cron que actualiza las relaciones entre facturas y tareas.
        Optimizado para reducir la carga de la base de datos.
        """
        _logger.info("Iniciando actualización programada de relaciones de facturas con tareas")
        
        yesterday = fields.Datetime.now() - timedelta(days=1)
        # Primero obtenemos las facturas modificadas con una búsqueda simple
        domain = [
            ('write_date', '>=', yesterday),
            ('move_type', 'in', ['out_invoice', 'out_refund'])
        ]
        # Limit the number of records per cron run and order
        moves = self.search(domain, limit=500, order='write_date desc')
        _logger.info(f"Cron job _cron_update_task_relations processing {len(moves)} invoices modified since {yesterday}.")

        count = 0
        processed_ids = []

        for move in moves:
            try:
                # The _compute_task_id method will be triggered automatically on write if dependencies change,
                # or by a direct call if needed. For a cron, we might want to force recomputation
                # if we suspect some relations were missed or to ensure correctness over time.
                # However, if _compute_task_id is stored and its deps are correct, direct recomputation
                # for all recent invoices might be redundant unless specifically needed for robustness.
                # The original cron was trying to manually sync task_id.
                # A simpler cron might just call `move.modified(['invoice_line_ids'])` or `move._compute_task_id()`
                # if we want to force recomputation.
                # For now, let's stick to the original intent of checking and updating if different.
                # This ensures that if `_compute_task_id` didn't fire for some reason, it's corrected.

                current_task_ids_in_db = set(move.task_id.ids) # Get current stored task_ids

                # Recalculate what task_ids *should* be based on current lines
                # This logic is similar to _compute_task_id but without direct assignment inside loop
                expected_task_ids_list = []
                for line in move.invoice_line_ids:
                    if line.task_id and line.task_id.project_id.importation:
                        expected_task_ids_list.append(line.task_id.id)
                    elif line.sale_id:
                        expected_task_ids_list.extend(
                            task.id 
                            for task in line.sale_id.task_ids 
                            if task.project_id.importation
                        )
                expected_task_ids_set = set(expected_task_ids_list)

                if expected_task_ids_set != current_task_ids_in_db:
                    # Use write with (6,0,...) to set the new list, this will trigger the compute if not already aligned.
                    move.write({'task_id': [(6, 0, list(expected_task_ids_set))]})
                    # Alternatively, if we are sure _compute_task_id is robust:
                    # move._compute_task_id() # This would re-run the compute method
                    count += 1
                    processed_ids.append(move.id)
                # Removed self.env.cr.commit() from here
                    
            except Exception as e:
                _logger.error(f"Error al procesar factura {move.id} en cron _cron_update_task_relations: {str(e)}")
                # self.env.cr.rollback() # Rollback is implicitly handled by Odoo per transaction
                
        if count > 0:
            _logger.info(f"Actualización de relaciones de tareas completada por cron. Se actualizaron {count} facturas. IDs: {processed_ids}")
        else:
            _logger.info("Actualización de relaciones de tareas por cron: No se requirieron actualizaciones para las facturas procesadas.")