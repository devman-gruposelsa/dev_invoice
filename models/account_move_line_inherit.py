# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

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

    fob_total = fields.Integer(
        string='Fob Total',
        help='Total FOB para esta línea de factura.',
    )

    calculate_custom = fields.Boolean(
        string='Calculo custom',
        help='Campo para indicar si se debe calcular el subtotal de forma personalizada.',
    )

    # Agregamos un campo para almacenar nuestro subtotal personalizado
    custom_subtotal = fields.Float(
        string='Subtotal Personalizado',
        compute='_compute_custom_subtotal',
        store=True,
    )

    @api.depends("quantity", "days_storage", "product_id", "calculate_custom")
    def _compute_price_unit(self):
        super()._compute_price_unit()
        for line in self:
            _logger.info(f"[CUSTOM DEBUG] Procesando línea ID: {line.id or 'nuevo'} - Producto: {line.product_id.display_name if line.product_id else 'N/A'}")

            if not line.move_id.pricelist_id:
                _logger.info("[CUSTOM DEBUG] No hay lista de precios. Se omite.")
                continue

            if line.calculate_custom and line.product_id:
                product = line.product_id
                _logger.info(f"[CUSTOM DEBUG] Aplica lógica personalizada para producto: {product.display_name}")

                usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
                rate = 1.0
                if usd_currency:
                    rate_data = usd_currency._get_rates(self.env.company, fields.Date.context_today(self))
                    rate = 1 / rate_data.get(usd_currency.id, 1.0)
                _logger.info(f"[CUSTOM DEBUG] Tasa de cambio USD: {rate}")

                if product.fob_total:
                    subtotal = line.fob_total * rate * 0.001
                    if subtotal < product.min_price:
                        line.update({
                            'price_unit': product.min_price,
                            'quantity': 1,
                        })
                    #     line._recompute_price()
                    # else:
                    #     line._recompute_price()

                elif product.is_storage:
                    subtotal = line.quantity * line.days_storage * line.price_unit
                    if subtotal < product.min_price:
                        unit_price = product.min_price / line.quantity if line.quantity else 0
                        line.update({
                            'price_unit': unit_price,
                        })
                    #     line._recompute_price()
                    # else:
                    #     line._recompute_price()
                
                # Cortamos para que no siga con pricelist
                continue

            # Si no aplica lógica custom, usamos pricelist
            _logger.info("[CUSTOM DEBUG] Aplica lógica de pricelist.")
            line.with_context(check_move_validity=False).price_unit = line._get_price_with_pricelist()

    @api.depends('quantity', 'price_unit', 'tax_ids', 'currency_id', 'product_id', 'days_storage', 'calculate_custom')
    def _compute_price_subtotal(self):
        super()._compute_price_subtotal()
        
        for line in self:
            if not line.calculate_custom or not line.product_id:
                continue

            _logger.info(f"[CUSTOM DEBUG] Calculando subtotal para línea {line.id} - Producto: {line.product_id.display_name}")
            
            product = line.product_id
            usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
            rate = 1.0
            
            if usd_currency:
                rate_data = usd_currency._get_rates(self.env.company, fields.Date.context_today(self))
                rate = 1 / rate_data.get(usd_currency.id, 1.0)
                _logger.info(f"[CUSTOM DEBUG] Tasa de cambio USD: {rate}")

            # Cálculo para productos FOB
            if product.product_tmpl_id.fob_total:
                subtotal = line.fob_total * rate * 0.001
                _logger.info(f"[CUSTOM DEBUG] Cálculo FOB - fob total: {line.fob_total} * Rate: {rate} * 0.001")
                
                if subtotal < product.product_tmpl_id.min_price:
                    subtotal = product.product_tmpl_id.min_price
                    _logger.info(f"[CUSTOM DEBUG] Se aplica precio mínimo: {subtotal}")

            # Cálculo para productos de almacenamiento
            elif product.product_tmpl_id.is_storage:
                subtotal = line.quantity * line.days_storage * line.price_unit
                _logger.info(f"[CUSTOM DEBUG] Cálculo Storage - Cantidad: {line.quantity} * Días: {line.days_storage} * Precio: {line.price_unit}")
                
                if subtotal < product.product_tmpl_id.min_price:
                    subtotal = product.product_tmpl_id.min_price
                    _logger.info(f"[CUSTOM DEBUG] Se aplica precio mínimo: {subtotal}")

            else:
                _logger.info("[CUSTOM DEBUG] No aplica cálculo especial")
                continue

            # Actualizamos el subtotal
            line.price_subtotal = subtotal
            _logger.info(f"[CUSTOM DEBUG] Subtotal final: {subtotal}")

    @api.depends('quantity', 'price_unit', 'product_id', 'days_storage', 'calculate_custom', 'move_id.currency_id', 'move_id.date')
    def _compute_custom_subtotal(self):
        for line in self:
            if not line.calculate_custom or not line.product_id:
                line.custom_subtotal = 0.0
                continue

            product = line.product_id
            
            # Obtener tasa de cambio
            usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
            rate = 1.0
            if usd_currency:
                rate_data = usd_currency._get_rates(self.env.company, line.move_id.date or fields.Date.context_today(self))
                rate = 1 / rate_data.get(usd_currency.id, 1.0)
                _logger.info(f"[CUSTOM DEBUG] Tasa de cambio USD: {rate}")

            # Cálculo para productos FOB
            if product.product_tmpl_id.fob_total:
                subtotal = line.fob_total * rate * 0.001
                _logger.info(f"[CUSTOM DEBUG] Cálculo FOB - fob total: {line.fob_total} * Rate: {rate} * 0.001 = {subtotal}")

                if subtotal < product.product_tmpl_id.min_price:
                    subtotal = product.product_tmpl_id.min_price
                    _logger.info(f"[CUSTOM DEBUG] Se aplica precio mínimo FOB: {subtotal}")

            # Cálculo para productos de almacenamiento
            elif product.product_tmpl_id.is_storage:
                subtotal = line.quantity * line.days_storage * line.price_unit
                _logger.info(f"[CUSTOM DEBUG] Cálculo Storage - Cantidad: {line.quantity} * Días: {line.days_storage} * Precio: {line.price_unit} = {subtotal}")
                
                if subtotal < product.product_tmpl_id.min_price:
                    subtotal = product.product_tmpl_id.min_price
                    _logger.info(f"[CUSTOM DEBUG] Se aplica precio mínimo Storage: {subtotal}")

            else:
                subtotal = line.price_unit * line.quantity
                _logger.info(f"[CUSTOM DEBUG] Cálculo normal: {subtotal}")

            line.custom_subtotal = subtotal

    def _get_computed_price(self):
        """Método para obtener el precio computado según el tipo de producto"""
        self.ensure_one()
        if not self.calculate_custom or not self.product_id:
            return self.price_unit

        product = self.product_id
        
        # Obtener tasa de cambio
        usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
        rate = 1.0
        if usd_currency:
            rate_data = usd_currency._get_rates(self.env.company, self.move_id.date or fields.Date.context_today(self))
            rate = 1 / rate_data.get(usd_currency.id, 1.0)

        if product.product_tmpl_id.fob_total:
            price = self.fob_total * rate * 0.001
            return max(price, product.product_tmpl_id.min_price)
        elif product.product_tmpl_id.is_storage:
            price = self.price_unit * self.days_storage
            return max(price, product.product_tmpl_id.min_price / self.quantity if self.quantity else 0)
        return self.price_unit

    @api.model
    def create(self, vals):
        res = super().create(vals)
        if res.calculate_custom:
            price = res._get_computed_price()
            if price != res.price_unit:
                res.with_context(check_move_validity=False).write({'price_unit': price})
        return res

    def write(self, vals):
        res = super().write(vals)
        if any(field in vals for field in ['calculate_custom', 'quantity', 'price_unit', 'days_storage']):
            for line in self:
                if line.calculate_custom:
                    price = line._get_computed_price()
                    if price != line.price_unit:
                        super(AccountMoveLineInherit, line.with_context(check_move_validity=False)).write({'price_unit': price})
        return res