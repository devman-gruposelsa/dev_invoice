# -*- coding: utf-8 -*-
from odoo import models, fields, api

import logging
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

class AccountMoveInherit(models.Model):
    _inherit = 'account.move'

    task_id = fields.Many2many('project.task', string='Carpeta de importación', compute='_compute_task_id', readonly=False)

    def _compute_task_id(self):
        for rec in self:
            task_ids = []
            _logger.info(f"Procesando cálculo de task_id para factura {rec.id}")
            for line in rec.invoice_line_ids:
                if line.task_id:
                    task_ids.append(line.task_id.id)
                    _logger.info(f"Línea {line.id} asociada a la tarea {line.task_id.id}")
                elif line.sale_id and line.sale_id.task_ids:
                    for task in line.sale_id.task_ids:
                        task_ids.append(task.id)
                        _logger.info(f"Orden de venta {line.sale_id.id} asociada a la tarea {task.id}")
            rec.task_id = [(6, 0, task_ids)]
            _logger.info(f"Tareas calculadas para factura {rec.id}: {task_ids}")

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

    def write(self, vals):
        res = super(AccountMoveInherit, self).write(vals)
        for rec in self:
            if rec.invoice_origin and 'Storage' in rec.invoice_origin.lower():
                if 'invoice_date' in vals and vals['invoice_date']:
                    _logger.info(f"Procesando cálculo de próxima fecha de facturación para factura {rec.id}")
                    for task in rec.task_id:
                        # Calcular la fecha 30 días después de la fecha de la factura
                        next_billing_date = fields.Date.from_string(vals['invoice_date']) + timedelta(days=30)
                        task.date_next_billing = next_billing_date
                        _logger.info(f"Actualizada la próxima fecha de facturación para la tarea {task.id}: {next_billing_date}")
                elif rec.invoice_date:
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