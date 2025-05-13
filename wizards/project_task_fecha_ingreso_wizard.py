from odoo import models, fields, api

class ProjectTaskFechaIngresoWizard(models.TransientModel):
    _name = 'project.task.fecha.ingreso.wizard'
    _description = 'Modificar Fecha de Ingreso'

    task_id = fields.Many2one('project.task', string="Tarea", required=True)
    fecha_ingreso = fields.Datetime(string="Fecha de Ingreso", required=True)

    def action_apply(self):
        self.task_id.write({'fecha_ingreso': self.fecha_ingreso})
        return {'type': 'ir.actions.act_window_close'}