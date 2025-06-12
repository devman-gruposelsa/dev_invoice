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

                elif product.is_storage:
                    subtotal = line.quantity * line.days_storage * line.price_unit
                    if subtotal < product.min_price:
                        # Aseguramos que el precio unitario resulte en el monto mínimo exacto
                        if line.quantity and line.days_storage:
                            new_price_unit = product.min_price / (line.quantity * line.days_storage)
                            # Ajustamos el precio unitario con más precisión decimal
                            line.with_context(check_move_validity=False).price_unit = round(new_price_unit, 6)
                            _logger.info(f"[CUSTOM DEBUG] Precio mínimo ajustado - Nuevo precio unitario: {new_price_unit}")
                
                continue

            _logger.info("[CUSTOM DEBUG] Aplica lógica de pricelist.")
            line.with_context(check_move_validity=False).price_unit = line._get_price_with_pricelist()

    @api.depends('quantity', 'price_unit', 'tax_ids', 'currency_id', 'product_id', 'days_storage', 'calculate_custom')
    def _compute_price_subtotal(self):
        super()._compute_price_subtotal()
        
        for line in self:
            if not line.calculate_custom or not line.product_id:
                continue

            product = line.product_id
            # currency = line.currency_id or line.move_id.company_id.currency_id # For rounding if not using .write

            if product.product_tmpl_id.is_storage:
                _logger.info(f"--- Debugging line ID {line.id}, Product: {product.display_name} (Storage) ---")
                partner = line.move_id.partner_id

                original_daily_rate = line.price_unit
                _logger.info(f"Line {line.id}: Initial original_daily_rate: {original_daily_rate}, Quantity: {line.quantity}, Days: {line.days_storage}")

                base_subtotal = line.quantity * line.days_storage * original_daily_rate
                _logger.info(f"Line {line.id}: Calculated base_subtotal: {base_subtotal}")

                if partner:
                    _logger.info(f"Line {line.id}: Partner ID: {partner.id}, Name: {partner.name}, no_minimum_pricing: {partner.no_minimum_pricing}")
                else:
                    _logger.info(f"Line {line.id}: No partner found on the invoice move.")

                if partner and partner.no_minimum_pricing:
                    _logger.info(f"Line {line.id}: 'no_minimum_pricing' is TRUE. Applying calculated base_subtotal.")
                    line.price_subtotal = line.currency_id.round(base_subtotal) if line.currency_id else round(base_subtotal, 2)
                    if line.price_unit != original_daily_rate: # Ensure price_unit is the true daily rate
                        line.price_unit = original_daily_rate
                    _logger.info(f"Line {line.id}: Set price_subtotal to {line.price_subtotal}, price_unit to {line.price_unit}. Skipping further minimum checks.")
                else:
                    _logger.info(f"Line {line.id}: 'no_minimum_pricing' is FALSE or no partner. Proceeding to check minimums.")
                    effective_min_price = 0.0
                    min_price_source = "None"

                    if partner:
                        special_min_rule = self.env['partner.product.special.minimum'].search([
                            ('partner_id', '=', partner.id),
                            ('product_id', '=', line.product_id.id),
                            ('company_id', '=', line.company_id.id or self.env.company.id)
                        ], limit=1)
                        if special_min_rule and special_min_rule.special_min_price > 0:
                            effective_min_price = special_min_rule.special_min_price
                            min_price_source = f"Partner Special ({effective_min_price})"
                            _logger.info(f"Line {line.id}: Found special minimum: {effective_min_price}")
                        else:
                            _logger.info(f"Line {line.id}: No special minimum found or special_min_price is 0 for partner {partner.name}.")

                    if effective_min_price == 0.0:
                        global_min_price = line.product_id.product_tmpl_id.min_price
                        _logger.info(f"Line {line.id}: Checking global minimum: {global_min_price}")
                        if global_min_price > 0:
                            effective_min_price = global_min_price
                            min_price_source = f"Product Global ({effective_min_price})"
                        else:
                            min_price_source = "None (Global not set or zero)"

                    _logger.info(f"Line {line.id}: Base subtotal: {base_subtotal}. Effective minimum price: {effective_min_price} from {min_price_source}.")

                    if effective_min_price > 0 and base_subtotal < effective_min_price:
                        _logger.info(f"Line {line.id}: Applying minimum price {effective_min_price}. Original price_unit: {original_daily_rate}, Original price_subtotal (calculated): {base_subtotal}")
                        adjusted_price_unit = 0.0
                        if line.quantity and line.days_storage:
                            adjusted_price_unit = round(effective_min_price / (line.quantity * line.days_storage), 6)
                        elif line.quantity:
                            adjusted_price_unit = round(effective_min_price / line.quantity, 6)
                        elif line.days_storage: # Added case if only days_storage is non-zero
                             adjusted_price_unit = round(effective_min_price / line.days_storage, 6)
                        elif effective_min_price > 0 : # Both quantity and days_storage are zero
                             adjusted_price_unit = effective_min_price

                        _logger.info(f"Line {line.id}: Calculated adjusted_price_unit: {adjusted_price_unit}. Current line.price_unit: {line.price_unit}, current line.price_subtotal: {line.price_subtotal}")

                        if line.price_unit != adjusted_price_unit or line.price_subtotal != effective_min_price:
                            _logger.info(f"Line {line.id}: Values differ, calling .write(). Target price_unit: {adjusted_price_unit}, Target price_subtotal: {effective_min_price}")
                            line.with_context(check_move_validity=False).write({
                                'price_unit': adjusted_price_unit,
                                'price_subtotal': effective_min_price
                            })
                            _logger.info(f"Line {line.id}: After .write(), line.price_unit: {line.price_unit}, line.price_subtotal: {line.price_subtotal}")
                        else:
                            _logger.info(f"Line {line.id}: Values already match target, .write() skipped. line.price_unit: {line.price_unit}, line.price_subtotal: {line.price_subtotal}")
                    else:
                        _logger.info(f"Line {line.id}: Minimum price NOT applied (effective_min_price is 0, or base_subtotal is sufficient). Current price_subtotal: {line.price_subtotal}, current price_unit: {line.price_unit}")
                        current_rounded_subtotal = line.currency_id.round(base_subtotal) if line.currency_id else round(base_subtotal, 2)
                        if line.price_subtotal != current_rounded_subtotal or line.price_unit != original_daily_rate:
                             _logger.info(f"Line {line.id}: Setting price_subtotal to {current_rounded_subtotal} and price_unit to {original_daily_rate}.")
                             line.price_subtotal = current_rounded_subtotal
                             line.price_unit = original_daily_rate
                        else:
                             _logger.info(f"Line {line.id}: price_subtotal and price_unit already match calculated values when no minimum applied.")
                _logger.info(f"--- Finished debugging line ID {line.id}, Product: {product.display_name} (Storage) ---")
                continue

            elif product.product_tmpl_id.fob_total:
                usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
                rate = 1.0
                if usd_currency:
                    company = line.move_id.company_id or self.env.company
                    date = line.move_id.date or fields.Date.context_today(line)
                    # Ensure rate_data is checked for the currency's existence
                    rate_data = usd_currency._get_rates(company, date)
                    if usd_currency.id in rate_data:
                         rate = 1 / rate_data[usd_currency.id]
                    else:
                        _logger.warning(f"Rate for USD not found for date {date} and company {company.name}. Defaulting to 1.0.")

                _logger.info(f"--- Debugging line ID {line.id}, Product: {product.display_name} (FOB) ---")
                calculated_fob_subtotal = (line.fob_total or 0.0) * rate * 0.001
                partner = line.move_id.partner_id
                final_subtotal = calculated_fob_subtotal

                if partner:
                    _logger.info(f"Line {line.id}: Partner ID: {partner.id}, Name: {partner.name}, no_minimum_pricing: {partner.no_minimum_pricing}")
                else:
                    _logger.info(f"Line {line.id}: No partner found on the invoice move.")

                if partner and partner.no_minimum_pricing:
                    _logger.info(f"Line {line.id}: 'no_minimum_pricing' is TRUE for FOB. Applying calculated subtotal: {final_subtotal}")
                    current_rounded_subtotal = line.currency_id.round(final_subtotal) if line.currency_id else round(final_subtotal, 2)
                    if line.price_subtotal != current_rounded_subtotal:
                        line.price_subtotal = current_rounded_subtotal
                else:
                    _logger.info(f"Line {line.id}: 'no_minimum_pricing' is FALSE or no partner for FOB. Proceeding to check minimums.")
                    effective_min_price = 0.0
                    min_price_source = "None"
                    if partner:
                        special_min_rule = self.env['partner.product.special.minimum'].search([
                            ('partner_id', '=', partner.id),
                            ('product_id', '=', line.product_id.id),
                            ('company_id', '=', line.company_id.id or self.env.company.id)
                        ], limit=1)
                        if special_min_rule and special_min_rule.special_min_price > 0:
                            effective_min_price = special_min_rule.special_min_price
                            min_price_source = f"Partner Special ({effective_min_price})"
                            _logger.info(f"Line {line.id}: Found special minimum for FOB: {effective_min_price}")
                        else:
                            _logger.info(f"Line {line.id}: No special minimum found or special_min_price is 0 for FOB partner {partner.name}.")

                    if effective_min_price == 0.0:
                        global_min_price = line.product_id.product_tmpl_id.min_price
                        _logger.info(f"Line {line.id}: Checking global minimum for FOB: {global_min_price}")
                        if global_min_price > 0:
                            effective_min_price = global_min_price
                            min_price_source = f"Product Global ({effective_min_price})"
                        else:
                             min_price_source = "None (Global not set or zero)"

                    _logger.info(f"Line {line.id} (FOB): Calculated subtotal: {calculated_fob_subtotal}. Effective minimum: {effective_min_price} from {min_price_source}.")

                    if effective_min_price > 0 and calculated_fob_subtotal < effective_min_price:
                        final_subtotal = effective_min_price
                        _logger.info(f"Line {line.id} (FOB): Applying minimum price {final_subtotal}.")
                    else:
                        _logger.info(f"Line {line.id} (FOB): Minimum price NOT applied or calculated subtotal is sufficient.")

                    current_rounded_subtotal = line.currency_id.round(final_subtotal) if line.currency_id else round(final_subtotal, 2)
                    if line.price_subtotal != current_rounded_subtotal:
                        line.price_subtotal = current_rounded_subtotal
                _logger.info(f"--- Finished debugging line ID {line.id}, Product: {product.display_name} (FOB) ---")
                continue

            # Fallback for other custom types if any, or if super() handled it.
            # If no specific custom logic applies here beyond what super() did, this is fine.

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
                _logger.info(f"--- Debugging CUSTOM_SUBTOTAL line ID {line.id}, Product: {product.display_name} (FOB) ---")
                subtotal = (line.fob_total or 0.0) * rate * 0.001
                partner = line.move_id.partner_id
                _logger.info(f"Line {line.id} (FOB): Calculated base subtotal for custom_subtotal: {subtotal}")

                if partner:
                    _logger.info(f"Line {line.id} (FOB): Partner ID: {partner.id}, Name: {partner.name}, no_minimum_pricing: {partner.no_minimum_pricing}")
                else:
                    _logger.info(f"Line {line.id} (FOB): No partner found on the invoice move.")

                if partner and partner.no_minimum_pricing:
                    _logger.info(f"Line {line.id} (FOB): 'no_minimum_pricing' is TRUE. Using calculated subtotal {subtotal} for custom_subtotal.")
                else:
                    _logger.info(f"Line {line.id} (FOB): 'no_minimum_pricing' is FALSE or no partner. Proceeding to check minimums for custom_subtotal.")
                    effective_min_price = 0.0
                    min_price_source = "None"
                    if partner:
                        special_min_rule = self.env['partner.product.special.minimum'].search([
                            ('partner_id', '=', partner.id),
                            ('product_id', '=', line.product_id.id),
                            ('company_id', '=', line.company_id.id or self.env.company.id)
                        ], limit=1)
                        if special_min_rule and special_min_rule.special_min_price > 0:
                            effective_min_price = special_min_rule.special_min_price
                            min_price_source = f"Partner Special ({effective_min_price})"
                            _logger.info(f"Line {line.id} (FOB): Found special minimum for custom_subtotal: {effective_min_price}")
                        else:
                            _logger.info(f"Line {line.id} (FOB): No special minimum for custom_subtotal for partner {partner.name}.")

                    if effective_min_price == 0.0:
                        global_min_price = line.product_id.product_tmpl_id.min_price
                        _logger.info(f"Line {line.id} (FOB): Checking global minimum for custom_subtotal: {global_min_price}")
                        if global_min_price > 0:
                            effective_min_price = global_min_price
                            min_price_source = f"Product Global ({effective_min_price})"
                        else:
                            min_price_source = "None (Global not set or zero)"

                    _logger.info(f"Line {line.id} (FOB): Base subtotal for custom_subtotal: {subtotal}. Effective minimum: {effective_min_price} from {min_price_source}.")
                    if effective_min_price > 0 and subtotal < effective_min_price:
                        subtotal = effective_min_price
                        _logger.info(f"Line {line.id} (FOB): Applied minimum price {subtotal} to custom_subtotal.")
                    else:
                        _logger.info(f"Line {line.id} (FOB): Minimum price NOT applied to custom_subtotal or subtotal is sufficient.")
                _logger.info(f"--- Finished debugging CUSTOM_SUBTOTAL line ID {line.id}, Product: {product.display_name} (FOB), Final custom_subtotal (before assignment): {subtotal} ---")

            elif product.product_tmpl_id.is_storage:
                _logger.info(f"--- Debugging CUSTOM_SUBTOTAL line ID {line.id}, Product: {product.display_name} (Storage) ---")
                original_daily_rate = line.price_unit # Crucial: use the price_unit that might have been adjusted by _compute_price_subtotal
                subtotal = line.quantity * line.days_storage * original_daily_rate
                partner = line.move_id.partner_id
                _logger.info(f"Line {line.id} (Storage): Initial original_daily_rate for custom_subtotal: {original_daily_rate}, Quantity: {line.quantity}, Days: {line.days_storage}. Calculated base subtotal: {subtotal}")

                if partner:
                    _logger.info(f"Line {line.id} (Storage): Partner ID: {partner.id}, Name: {partner.name}, no_minimum_pricing: {partner.no_minimum_pricing}")
                else:
                    _logger.info(f"Line {line.id} (Storage): No partner found on the invoice move.")

                if partner and partner.no_minimum_pricing:
                    _logger.info(f"Line {line.id} (Storage): 'no_minimum_pricing' is TRUE. Using calculated subtotal {subtotal} for custom_subtotal.")
                else:
                    _logger.info(f"Line {line.id} (Storage): 'no_minimum_pricing' is FALSE or no partner. Proceeding to check minimums for custom_subtotal.")
                    effective_min_price = 0.0
                    min_price_source = "None"
                    if partner:
                        special_min_rule = self.env['partner.product.special.minimum'].search([
                            ('partner_id', '=', partner.id),
                            ('product_id', '=', line.product_id.id),
                            ('company_id', '=', line.company_id.id or self.env.company.id)
                        ], limit=1)
                        if special_min_rule and special_min_rule.special_min_price > 0:
                            effective_min_price = special_min_rule.special_min_price
                            min_price_source = f"Partner Special ({effective_min_price})"
                            _logger.info(f"Line {line.id} (Storage): Found special minimum for custom_subtotal: {effective_min_price}")
                        else:
                             _logger.info(f"Line {line.id} (Storage): No special minimum for custom_subtotal for partner {partner.name}.")

                    if effective_min_price == 0.0:
                        global_min_price = line.product_id.product_tmpl_id.min_price
                        _logger.info(f"Line {line.id} (Storage): Checking global minimum for custom_subtotal: {global_min_price}")
                        if global_min_price > 0:
                            effective_min_price = global_min_price
                            min_price_source = f"Product Global ({effective_min_price})"
                        else:
                            min_price_source = "None (Global not set or zero)"

                    _logger.info(f"Line {line.id} (Storage): Base subtotal for custom_subtotal: {subtotal}. Effective minimum: {effective_min_price} from {min_price_source}.")
                    if effective_min_price > 0 and subtotal < effective_min_price:
                        subtotal = effective_min_price
                        _logger.info(f"Line {line.id} (Storage): Applied minimum price {subtotal} to custom_subtotal.")
                    else:
                        _logger.info(f"Line {line.id} (Storage): Minimum price NOT applied to custom_subtotal or subtotal is sufficient.")
                _logger.info(f"--- Finished debugging CUSTOM_SUBTOTAL line ID {line.id}, Product: {product.display_name} (Storage), Final custom_subtotal (before assignment): {subtotal} ---")
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