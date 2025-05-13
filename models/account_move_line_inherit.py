# -*- coding: utf-8 -*-
from odoo import models, fields, api

class AccountMoveLineInherit(models.Model):
    _inherit = 'account.move.line'

    task_id = fields.Many2one(
        'project.task',
        string='Tarea Relacionada',
        help='Tarea relacionada con esta línea de factura.',
    )

    days_storage = fields.Integer(
        string='Días de almacenamiento',
        help='Días de almacenamiento para esta línea de factura.',
    )

    calculate_custom = fields.Boolean(
        string='Calculo custom',
        help='Campo para indicar si se debe calcular el subtotal de forma personalizada.',
    )

    # price_subtotal = fields.Float(
    #     string='Subtotal calculado',
    #     store=True,  # Se almacena en la BD, pero sin cálculo automático
    #     help='Subtotal calculado basado en quantity, days_storage, price_unit y min_price.',
    # )

    # def _calculate_price_subtotal(self, line):
    #     """Método auxiliar para calcular el subtotal."""
    #     effective_days = line.days_storage if line.days_storage > 0 else 1
    #     calculated_price = line.quantity * effective_days * line.price_unit
    #     min_price = line.product_id.min_price if line.product_id else 0
    #     return max(calculated_price, min_price)

    # @api.model
    # def create(self, vals):
    #     """Calcular price_subtotal solo si no está en los valores proporcionados."""
    #     if 'price_subtotal' not in vals:
    #         temp_record = self.new(vals)  # Crear un objeto temporal sin guardar en BD
    #         vals['price_subtotal'] = self._calculate_price_subtotal(temp_record)
    #     return super(AccountMoveLineInherit, self).create(vals)

    # def write(self, vals):
    #     """Actualizar price_subtotal solo si no se está modificando manualmente."""
    #     if 'price_subtotal' not in vals:
    #         for line in self:
    #             vals['price_subtotal'] = self._calculate_price_subtotal(line)
    #     return super(AccountMoveLineInherit, self).write(vals)


