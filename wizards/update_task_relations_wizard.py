from odoo import models, api
import logging

_logger = logging.getLogger(__name__)

class UpdateTaskRelationsWizard(models.TransientModel):
    _name = 'update.task.relations.wizard'
    _description = 'Actualizar relaciones de tareas en facturas'

    def action_update_relations(self):
        moves = self.env['account.move'].search([])
        for move in moves:
            try:
                move._update_task_relations()
                self.env.cr.commit()
                _logger.info(f"Actualizada factura ID: {move.id}")
            except Exception as e:
                _logger.error(f"Error en factura ID {move.id}: {str(e)}")
                self.env.cr.rollback()
        return {'type': 'ir.actions.act_window_close'}