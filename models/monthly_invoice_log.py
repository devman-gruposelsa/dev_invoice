# -*- coding: utf-8 -*-
from odoo import models, fields, api


class MonthlyInvoiceLog(models.Model):
    _name = 'monthly.invoice.log'
    _description = 'Log de Facturación Mensual Automática'
    _order = 'execution_date desc, id desc'

    name = fields.Char(
        string='Nombre',
        compute='_compute_name',
        store=True
    )
    execution_date = fields.Datetime(
        string='Fecha de Ejecución',
        default=fields.Datetime.now,
        readonly=True
    )
    user_id = fields.Many2one(
        'res.users',
        string='Usuario',
        default=lambda self: self.env.user,
        readonly=True
    )
    tasks_found = fields.Integer(
        string='Tareas Encontradas',
        readonly=True
    )
    tasks_processed = fields.Integer(
        string='Tareas Procesadas',
        readonly=True
    )
    invoices_created = fields.Integer(
        string='Facturas Creadas',
        readonly=True
    )
    state = fields.Selection([
        ('success', 'Exitoso'),
        ('partial', 'Parcial'),
        ('error', 'Error'),
    ], string='Estado', readonly=True, default='success')
    
    origin = fields.Selection([
        ('cron', 'Automático (Cron)'),
        ('manual', 'Manual (Usuario)'),
    ], string='Origen', readonly=True, default='manual')
    
    notes = fields.Text(
        string='Notas / Resumen',
        readonly=True
    )
    error_message = fields.Text(
        string='Mensaje de Error',
        readonly=True
    )
    
    # Relaciones
    task_ids = fields.Many2many(
        'project.task',
        'monthly_invoice_log_task_rel',
        'log_id',
        'task_id',
        string='Tareas Facturadas',
        readonly=True
    )
    invoice_ids = fields.Many2many(
        'account.move',
        'monthly_invoice_log_move_rel',
        'log_id',
        'move_id',
        string='Facturas Generadas',
        readonly=True
    )

    @api.depends('execution_date', 'origin')
    def _compute_name(self):
        for record in self:
            origin_label = 'CRON' if record.origin == 'cron' else 'MANUAL'
            if record.execution_date:
                record.name = f"[{origin_label}] Facturación Mensual - {record.execution_date.strftime('%d/%m/%Y %H:%M')}"
            else:
                record.name = f"[{origin_label}] Facturación Mensual"

    def action_view_tasks(self):
        """Abrir vista de tareas relacionadas"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Tareas Facturadas',
            'res_model': 'project.task',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.task_ids.ids)],
            'context': {'create': False},
        }

    def action_view_invoices(self):
        """Abrir vista de facturas relacionadas"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Facturas Generadas',
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.invoice_ids.ids)],
            'context': {'create': False},
        }
