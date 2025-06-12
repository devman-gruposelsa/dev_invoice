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

    def _get_effective_minimum_price(self, product, partner):
        """Helper method to get effective minimum price considering partner special rules"""
        if not partner or partner.no_minimum_pricing:
            return 0.0

        # Buscar regla especial para el partner
        special_min_rule = self.env['partner.product.special.minimum'].search([
            ('partner_id', '=', partner.id),
            ('product_id', '=', product.id),
            ('company_id', '=', self.company_id.id or self.env.company.id)
        ], limit=1)

        if special_min_rule and special_min_rule.special_min_price > 0:
            return special_min_rule.special_min_price
        
        return product.product_tmpl_id.min_price or 0.0

    @api.depends('quantity', 'price_unit', 'product_id', 'days_storage', 'calculate_custom', 'move_id.currency_id', 'move_id.date')
    def _compute_custom_subtotal(self):
        for line in self:
            if not line.calculate_custom or not line.product_id:
                line.custom_subtotal = 0.0
                continue

            product = line.product_id
            partner = line.move_id.partner_id
            days = line.days_storage or 1
            
            _logger.info(f"Calculando subtotal para producto {product.name} - días: {days}")
            
            if product.product_tmpl_id.is_storage:
                # Obtener precio de la lista de precios
                pricelist = line.move_id.pricelist_id
                if pricelist:
                    daily_rate = pricelist._get_product_price(
                        product,
                        quantity=1.0,
                        uom=product.uom_id,
                        date=line.move_id.date
                    )
                else:
                    daily_rate = product.list_price

                # Calcular subtotales y precio por día
                original_quantity = line.quantity
                price_per_day = daily_rate * days
                base_subtotal = original_quantity * price_per_day

                _logger.info(f"Cálculos para almacenaje: daily_rate={daily_rate}, days={days}, price_per_day={price_per_day}, base_subtotal={base_subtotal}")

                # Si el partner tiene no_minimum_pricing, el precio es days * precio lista
                if partner and partner.no_minimum_pricing:
                    _logger.info(f"Partner {partner.name} tiene no_minimum_pricing=True")
                    line.with_context(check_move_validity=False).write({
                        'price_unit': price_per_day,
                        'quantity': original_quantity
                    })
                    subtotal = base_subtotal
                else:
                    # Buscar regla especial para el partner
                    special_min_rule = self.env['partner.product.special.minimum'].search([
                        ('partner_id', '=', partner.id),
                        ('product_id', '=', product.id),
                        ('company_id', '=', self.company_id.id or self.env.company.id)
                    ], limit=1)

                    # Determinar el precio mínimo efectivo
                    if special_min_rule and special_min_rule.special_min_price > 0:
                        effective_min_price = special_min_rule.special_min_price
                    else:
                        effective_min_price = product.product_tmpl_id.min_price or 0.0

                    # Aplicar lógica de precios mínimos
                    if effective_min_price > 0 and base_subtotal < effective_min_price:
                        _logger.info(f"Aplicando precio mínimo efectivo: {effective_min_price}")
                        line.with_context(check_move_validity=False).write({
                            'price_unit': effective_min_price,
                            'quantity': 1.0
                        })
                        subtotal = effective_min_price
                    else:
                        line.with_context(check_move_validity=False).write({
                            'price_unit': price_per_day,
                            'quantity': original_quantity
                        })
                        subtotal = base_subtotal

            elif product.product_tmpl_id.fob_total:
                usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
                rate = 1.0
                if usd_currency:
                    rate_data = usd_currency._get_rates(self.env.company, line.move_id.date or fields.Date.context_today(self))
                    rate = 1 / rate_data.get(usd_currency.id, 1.0)

                # Cálculo FOB
                fob_amount = (line.fob_total or 0.0) * rate * 0.001
                line.with_context(check_move_validity=False).write({'price_unit': fob_amount})
                
                if partner and partner.no_minimum_pricing:
                    subtotal = fob_amount * line.quantity
                else:
                    # Si no tiene no_minimum_pricing, verificar mínimo
                    if fob_amount < product.product_tmpl_id.min_price:
                        line.with_context(check_move_validity=False).write({
                            'price_unit': product.product_tmpl_id.min_price,
                            'quantity': 1
                        })
                        subtotal = product.product_tmpl_id.min_price
                    else:
                        subtotal = fob_amount * line.quantity
            else:
                subtotal = line.price_unit * line.quantity

            line.custom_subtotal = subtotal

    @api.depends("quantity", "days_storage", "product_id", "calculate_custom")
    def _compute_price_unit(self):
        super()._compute_price_unit()
        for line in self:
            if not line.calculate_custom or not line.product_id:
                continue

            product = line.product_id
            partner = line.move_id.partner_id
            effective_min_price = self._get_effective_minimum_price(product, partner)

            if product.product_tmpl_id.is_storage:
                base_subtotal = line.quantity * (line.days_storage or 1) * line.price_unit
                
                if effective_min_price > 0 and base_subtotal < effective_min_price:
                    line.with_context(check_move_validity=False).write({
                        'quantity': 1,
                        'price_unit': effective_min_price
                    })

            elif product.product_tmpl_id.fob_total:
                usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
                rate = 1.0
                if usd_currency:
                    rate_data = usd_currency._get_rates(self.env.company, fields.Date.context_today(self))
                    rate = 1 / rate_data.get(usd_currency.id, 1.0)

                base_subtotal = (line.fob_total or 0.0) * rate * 0.001
                
                if effective_min_price > 0 and base_subtotal < effective_min_price:
                    line.with_context(check_move_validity=False).write({
                        'quantity': 1,
                        'price_unit': effective_min_price
                    })

    @api.depends('quantity', 'price_unit', 'tax_ids', 'currency_id', 'product_id', 'days_storage', 'calculate_custom')
    def _compute_price_subtotal(self):
        super()._compute_price_subtotal()
        
        for line in self:
            if not line.calculate_custom or not line.product_id:
                continue

            product = line.product_id
            if product.product_tmpl_id.is_storage:
                partner = line.move_id.partner_id
                daily_rate = product.list_price
                original_quantity = line.quantity
                days = line.days_storage or 1
                
                base_subtotal = original_quantity * days * daily_rate

                if partner and partner.no_minimum_pricing:
                    # Con no_minimum_pricing mantener cantidad y ajustar precio
                    new_price_unit = daily_rate * days
                    line.with_context(check_move_validity=False).write({
                        'price_unit': new_price_unit,
                        'quantity': original_quantity,
                        'price_subtotal': base_subtotal
                    })
                else:
                    # Sin no_minimum_pricing
                    effective_min_price = self._get_effective_minimum_price(product, partner)
                    if effective_min_price > 0 and base_subtotal < effective_min_price:
                        line.with_context(check_move_validity=False).write({
                            'price_unit': effective_min_price,
                            'quantity': 1,
                            'price_subtotal': effective_min_price
                        })
                    else:
                        new_price_unit = daily_rate * days
                        line.with_context(check_move_validity=False).write({
                            'price_unit': new_price_unit,
                            'quantity': original_quantity,
                            'price_subtotal': base_subtotal
                        })
                continue

            _logger.info(f"Line {line.id}: No custom calculation applied, using super() result.")
            # Si no se aplica el cálculo personalizado, se puede dejar que el super() maneje el comportamiento normal.
            # Esto es especialmente importante si hay lógica en el método padre que debe ejecutarse.
            super(AccountMoveLineInherit, line).write({
                'price_subtotal': line.price_unit * line.quantity,
            })

    def _get_computed_price(self):
        """Método para obtener el precio computado según el tipo de producto"""
        self.ensure_one()
        if not self.calculate_custom or not self.product_id:
            return self.price_unit

        product = self.product_id
        partner = self.move_id.partner_id

        if product.product_tmpl_id.fob_total:
            usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
            rate = 1.0
            if usd_currency:
                rate_data = usd_currency._get_rates(self.env.company, fields.Date.context_today(self))
                rate = 1 / rate_data.get(usd_currency.id, 1.0)
        
            # Cálculo FOB
            calculated_price = self.fob_total * rate * 0.001
            
            # Si tiene no_minimum_pricing, retornar el precio calculado sin importar el mínimo
            if partner and partner.no_minimum_pricing:
                return calculated_price
                
            # Si no tiene no_minimum_pricing, verificar mínimo
            if calculated_price < product.product_tmpl_id.min_price:
                return product.product_tmpl_id.min_price
            return calculated_price
        
        elif product.product_tmpl_id.is_storage:
            list_price = product.list_price
            quantity = self.quantity
            days = self.days_storage
            
            # Calcular subtotal base
            base_subtotal = quantity * days * list_price
            
            # Si tiene no_minimum_pricing, ajustar el precio unitario para llegar al subtotal calculado
            if partner and partner.no_minimum_pricing:
                if quantity and days:
                    return base_subtotal / (quantity * days)
                return list_price
            
            # Si no tiene no_minimum_pricing y no supera el mínimo, retornar el precio mínimo
            min_price = product.product_tmpl_id.min_price
            if base_subtotal < min_price:
                return min_price
                
            # Si supera el mínimo, retornar precio ajustado para llegar al subtotal
            if quantity and days:
                return base_subtotal / (quantity * days)
            return list_price

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
                if line.calculate_custom and not line.move_id.partner_id.no_minimum_pricing:
                    # Solo procesar lógica de precio mínimo si no tiene no_minimum_pricing
                    price = line._get_computed_price()
                    update_vals = {}
                    
                    if price != line.price_unit:
                        update_vals['price_unit'] = price
                    
                    if line.product_id.product_tmpl_id.is_storage:
                        # Para productos de almacenamiento, verificar el subtotal
                        daily_rate = price / (line.days_storage or 1)
                        base_subtotal = line.quantity * (line.days_storage or 1) * daily_rate

                        # Buscar regla especial para el partner
                        special_min_rule = self.env['partner.product.special.minimum'].search([
                            ('partner_id', '=', line.move_id.partner_id.id),
                            ('product_id', '=', line.product_id.id),
                            ('company_id', '=', line.company_id.id or self.env.company.id)
                        ], limit=1)

                        if special_min_rule and special_min_rule.special_min_price > 0:
                            min_price = special_min_rule.special_min_price
                        else:
                            min_price = line.product_id.product_tmpl_id.min_price or 0.0

                        if min_price and base_subtotal < min_price:
                            update_vals.update({
                                'quantity': 1,
                                'price_unit': min_price
                            })

                    elif line.product_id.product_tmpl_id.fob_total:
                        # Para productos FOB
                        usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
                        rate = 1.0
                        if usd_currency:
                            rate_data = usd_currency._get_rates(self.env.company, fields.Date.context_today(self))
                            rate = 1 / rate_data.get(usd_currency.id, 1.0)
                        base_subtotal = (line.fob_total or 0.0) * rate * 0.001

                        # Buscar regla especial para el partner
                        special_min_rule = self.env['partner.product.special.minimum'].search([
                            ('partner_id', '=', line.move_id.partner_id.id),
                            ('product_id', '=', line.product_id.id),
                            ('company_id', '=', line.company_id.id or self.env.company.id)
                        ], limit=1)

                        if special_min_rule and special_min_rule.special_min_price > 0:
                            min_price = special_min_rule.special_min_price
                        else:
                            min_price = line.product_id.product_tmpl_id.min_price or 0.0

                        if min_price and base_subtotal < min_price:
                            update_vals.update({
                                'quantity': 1,
                                'price_unit': min_price
                            })

                    if update_vals:
                        super(AccountMoveLineInherit, line.with_context(check_move_validity=False)).write(update_vals)
        return res