from odoo import models, fields, api

class ProjectTaskDaysInvoicedWizard(models.TransientModel):
    _name = 'project.task.days.invoiced.wizard'
    _description = 'Modificar Días Facturados'

    task_id = fields.Many2one('project.task', string="Tarea", required=True)
    days_invoiced = fields.Integer(string="Días Facturados", required=True)

    def action_apply(self):
        self.task_id.write({'days_invoiced': self.days_invoiced})
        return {'type': 'ir.actions.act_window_close'}
