# -*- coding: utf-8 -*-
from odoo import models, fields

import logging

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
