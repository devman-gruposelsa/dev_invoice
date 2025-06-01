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
                original_daily_rate = line.price_unit # Assumed to be set by pricelist logic from project_task
                base_subtotal = line.quantity * line.days_storage * original_daily_rate
                partner = line.move_id.partner_id

                if partner and partner.no_minimum_pricing:
                    _logger.info(f"[CUSTOM DEBUG _compute_price_subtotal] Storage Line {line.id} - Partner: {partner.name} has 'no_minimum_pricing'. Setting subtotal to calculated {base_subtotal}, ensuring price_unit is daily rate {original_daily_rate}.")
                    # Directly assign to ensure values are set without triggering .write() related to minimums
                    # Ensure price_unit is the true daily rate, not one adjusted by prior minimum application attempts this cycle
                    if line.price_unit != original_daily_rate:
                        line.price_unit = original_daily_rate

                    current_rounded_subtotal = line.currency_id.round(base_subtotal) if line.currency_id else round(base_subtotal, 2)
                    if line.price_subtotal != current_rounded_subtotal:
                        line.price_subtotal = current_rounded_subtotal
                else:
                    # Partner allows minimums (or no partner), proceed with min price logic
                    effective_min_price = 0.0
                    min_price_source = "None (No applicable minimum)"

                    # Determine effective_min_price (special or global)
                    if partner: # Check for special minimum only if partner exists
                        special_min_rule = self.env['partner.product.special.minimum'].search([
                            ('partner_id', '=', partner.id),
                            ('product_id', '=', line.product_id.id),
                            ('company_id', '=', line.company_id.id or self.env.company.id)
                        ], limit=1)
                        if special_min_rule and special_min_rule.special_min_price > 0:
                            effective_min_price = special_min_rule.special_min_price
                            min_price_source = f"Special ({effective_min_price})"

                    if not effective_min_price or effective_min_price <= 0: # If no special rule, or special rule is 0, try global
                        global_min_price = line.product_id.product_tmpl_id.min_price
                        if global_min_price > 0: # Only consider it if set
                            effective_min_price = global_min_price
                            min_price_source = f"Global ({effective_min_price})"

                    _logger.info(f"[CUSTOM DEBUG _compute_price_subtotal] Storage Line {line.id} - Partner: {partner.name if partner else 'N/A'}, Product: {product.display_name}, BaseSubtotal: {base_subtotal}, EffectiveMinPrice: {effective_min_price}, Source: {min_price_source}")

                    if effective_min_price > 0 and base_subtotal < effective_min_price:
                        _logger.info(f"    Applying minimum price {effective_min_price}.")
                        adjusted_price_unit = 0.0
                        if line.quantity and line.days_storage:
                            adjusted_price_unit = round(effective_min_price / (line.quantity * line.days_storage), 6)
                        elif line.quantity: # If only days_storage is zero
                            adjusted_price_unit = round(effective_min_price / line.quantity, 6)
                        # Note: if quantity is also zero, adjusted_price_unit remains 0.0 unless product price is set to effective_min_price itself.
                        # This case (qty=0, days=0 but min_price exists) is ambiguous.

                        # Only call .write() if values actually need to change
                        if line.price_unit != adjusted_price_unit or line.price_subtotal != effective_min_price:
                            line.with_context(check_move_validity=False).write({
                                'price_unit': adjusted_price_unit,
                                'price_subtotal': effective_min_price
                            })
                    else:
                        _logger.info(f"    Minimum price not applied or base subtotal is sufficient. Setting subtotal to {base_subtotal}, ensuring price_unit is daily rate {original_daily_rate}.")
                        # Ensure price_unit is the true daily rate if min price logic not applied or bypassed
                        if line.price_unit != original_daily_rate:
                             line.price_unit = original_daily_rate
                        current_rounded_subtotal = line.currency_id.round(base_subtotal) if line.currency_id else round(base_subtotal, 2)
                        if line.price_subtotal != current_rounded_subtotal:
                            line.price_subtotal = current_rounded_subtotal
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

                calculated_fob_subtotal = (line.fob_total or 0.0) * rate * 0.001
                partner = line.move_id.partner_id
                final_subtotal = calculated_fob_subtotal

                if partner and partner.no_minimum_pricing:
                    _logger.info(f"[CUSTOM DEBUG _compute_price_subtotal] FOB Line {line.id} - Partner: {partner.name} has 'no_minimum_pricing'. Setting subtotal to calculated {final_subtotal}.")
                    current_rounded_subtotal = line.currency_id.round(final_subtotal) if line.currency_id else round(final_subtotal, 2)
                    if line.price_subtotal != current_rounded_subtotal:
                        line.price_subtotal = current_rounded_subtotal
                else:
                    effective_min_price = 0.0
                    min_price_source = "None (No applicable minimum)"
                    if partner:
                        special_min_rule = self.env['partner.product.special.minimum'].search([
                            ('partner_id', '=', partner.id),
                            ('product_id', '=', line.product_id.id),
                            ('company_id', '=', line.company_id.id or self.env.company.id)
                        ], limit=1)
                        if special_min_rule and special_min_rule.special_min_price > 0:
                            effective_min_price = special_min_rule.special_min_price
                            min_price_source = f"Special ({effective_min_price})"

                    if not effective_min_price or effective_min_price <= 0: # If no special rule or special rule is 0
                        global_min_price = line.product_id.product_tmpl_id.min_price
                        if global_min_price > 0:
                            effective_min_price = global_min_price
                            min_price_source = f"Global ({effective_min_price})"

                    _logger.info(f"[CUSTOM DEBUG _compute_price_subtotal] FOB Line {line.id} - Partner: {partner.name if partner else 'N/A'}, Product: {product.display_name}, CalculatedFOBSubtotal: {calculated_fob_subtotal}, EffectiveMinPrice: {effective_min_price}, Source: {min_price_source}")

                    if effective_min_price > 0 and calculated_fob_subtotal < effective_min_price:
                        final_subtotal = effective_min_price
                        _logger.info(f"    Applied minimum price: {effective_min_price} (Source: {min_price_source})")
                    else:
                        _logger.info(f"    No minimum price applied or calculated_fob_subtotal is greater. (MinPrice source: {min_price_source})")

                    current_rounded_subtotal = line.currency_id.round(final_subtotal) if line.currency_id else round(final_subtotal, 2)
                    if line.price_subtotal != current_rounded_subtotal:
                        line.price_subtotal = current_rounded_subtotal
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
                subtotal = (line.fob_total or 0.0) * rate * 0.001
                partner = line.move_id.partner_id

                if partner and partner.no_minimum_pricing:
                    _logger.info(f"[CUSTOM DEBUG _compute_custom_subtotal] FOB Line {line.id} - Partner: {partner.name} has 'no_minimum_pricing'. Calculated subtotal: {subtotal}")
                else:
                    # Partner allows minimums (or no partner), proceed with min price logic
                    effective_min_price = 0.0
                    min_price_source = "None (No applicable minimum)"
                    if partner: # Check for special minimum only if partner exists
                        special_min_rule = self.env['partner.product.special.minimum'].search([
                            ('partner_id', '=', partner.id),
                            ('product_id', '=', line.product_id.id),
                            ('company_id', '=', line.company_id.id or self.env.company.id)
                        ], limit=1)
                        if special_min_rule and special_min_rule.special_min_price > 0:
                            effective_min_price = special_min_rule.special_min_price
                            min_price_source = f"Special ({effective_min_price})"

                    if not effective_min_price or effective_min_price <= 0: # If no special rule or special rule is 0
                        global_min_price = line.product_id.product_tmpl_id.min_price
                        if global_min_price > 0:
                            effective_min_price = global_min_price
                            min_price_source = f"Global ({effective_min_price})"

                    _logger.info(f"[CUSTOM DEBUG _compute_custom_subtotal] FOB Line {line.id} - Calculated: {subtotal}, EffectiveMin: {effective_min_price}, Source: {min_price_source}")
                    if effective_min_price > 0 and subtotal < effective_min_price:
                        subtotal = effective_min_price
                        _logger.info(f"    Applied minimum {effective_min_price} to custom_subtotal.")
                # 'subtotal' for FOB is now set

            elif product.product_tmpl_id.is_storage:
                # Assuming line.price_unit is the original daily rate for this calculation context
                subtotal = line.quantity * line.days_storage * line.price_unit
                partner = line.move_id.partner_id

                if partner and partner.no_minimum_pricing:
                    _logger.info(f"[CUSTOM DEBUG _compute_custom_subtotal] Storage Line {line.id} - Partner: {partner.name} has 'no_minimum_pricing'. Calculated subtotal: {subtotal}")
                else:
                    # Partner allows minimums (or no partner), proceed with min price logic
                    effective_min_price = 0.0
                    min_price_source = "None (No applicable minimum)"
                    if partner: # Check for special minimum only if partner exists
                        special_min_rule = self.env['partner.product.special.minimum'].search([
                            ('partner_id', '=', partner.id),
                            ('product_id', '=', line.product_id.id),
                            ('company_id', '=', line.company_id.id or self.env.company.id)
                        ], limit=1)
                        if special_min_rule and special_min_rule.special_min_price > 0:
                            effective_min_price = special_min_rule.special_min_price
                            min_price_source = f"Special ({effective_min_price})"

                    if not effective_min_price or effective_min_price <= 0: # If no special rule or special rule is 0
                        global_min_price = line.product_id.product_tmpl_id.min_price
                        if global_min_price > 0:
                            effective_min_price = global_min_price
                            min_price_source = f"Global ({effective_min_price})"

                    _logger.info(f"[CUSTOM DEBUG _compute_custom_subtotal] Storage Line {line.id} - Calculated: {subtotal}, EffectiveMin: {effective_min_price}, Source: {min_price_source}")
                    if effective_min_price > 0 and subtotal < effective_min_price:
                        subtotal = effective_min_price
                        _logger.info(f"    Applied minimum {effective_min_price} to custom_subtotal.")
                # 'subtotal' for Storage is now set
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