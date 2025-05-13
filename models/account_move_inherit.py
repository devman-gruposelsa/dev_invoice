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
                             store=True)

    @api.depends('invoice_line_ids.task_id', 'invoice_line_ids.sale_id.task_ids')
    def _compute_task_id(self):
        for rec in self:
            task_ids = []
            _logger.info(f"Procesando cálculo de task_id para factura {rec.id}")
            for line in rec.invoice_line_ids:
                # Primero verificamos si la línea tiene una tarea directamente asociada
                if line.task_id and line.task_id.project_id.importation:
                    # Solo agregar tareas cuyo project_id tiene importation=True
                    task_ids.append(line.task_id.id)
                # Si no tiene tarea directa pero tiene orden de venta, buscamos en las tareas de la orden
                elif line.sale_id:
                    task_ids.extend(
                        task.id 
                        for task in line.sale_id.task_ids 
                        if task.project_id.importation
                    )
            
            # Eliminamos duplicados y asignamos las tareas
            rec.task_id = [(6, 0, list(set(task_ids)))]

    @api.model
    def create(self, vals):
        record = super(AccountMoveInherit, self).create(vals)
        record._update_task_relations()
        return record

    def write(self, vals):
        res = super(AccountMoveInherit, self).write(vals)
        if 'invoice_line_ids' in vals:
            self._update_task_relations()
        return res

    def _update_task_relations(self):
        """
        Actualiza las relaciones de tareas solo cuando es necesario
        """
        for rec in self:
            task_ids = []
            _logger.info(f"Actualizando relaciones de tareas para factura {rec.id}")
            for line in rec.invoice_line_ids:
                if line.task_id and line.task_id.project_id.importation:
                    task_ids.append(line.task_id.id)
                    _logger.info(f"Línea {line.id} asociada a la tarea {line.task_id.id}")
                elif line.sale_id and line.sale_id.task_ids:
                    for task in line.sale_id.task_ids:
                        if task.project_id.importation:
                            task_ids.append(task.id)
                            _logger.info(f"Orden de venta {line.sale_id.id} asociada a la tarea {task.id}")
            
            if set(task_ids) != set(rec.task_id.ids):
                rec.task_id = [(6, 0, task_ids)]
                _logger.info(f"Tareas actualizadas para factura {rec.id}: {task_ids}")

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
        Método para ser llamado por el cron que actualiza las relaciones entre facturas y tareas
        """
        _logger.info("Iniciando actualización programada de relaciones de facturas con tareas")
        moves = self.search([])
        count = 0
        
        for move in moves:
            try:
                task_ids = []
                for line in move.invoice_line_ids:
                    if line.task_id and line.task_id.project_id.importation:
                        task_ids.append(line.task_id.id)
                    elif line.sale_id and line.sale_id.task_ids:
                        task_ids.extend(
                            task.id 
                            for task in line.sale_id.task_ids 
                            if task.project_id.importation
                        )
                
                if set(task_ids) != set(move.task_id.ids):
                    move.task_id = [(6, 0, list(set(task_ids)))]
                    count += 1
                    self.env.cr.commit()  # Commit por cada actualización exitosa
                    
            except Exception as e:
                _logger.error(f"Error al procesar factura {move.id}: {str(e)}")
                self.env.cr.rollback()
                
        _logger.info(f"Actualización completada. Se actualizaron {count} facturas")