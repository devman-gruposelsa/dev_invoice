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

                # CASO 1: Partner tiene no_minimum_pricing = True
                if partner and partner.no_minimum_pricing:
                    
                    # Buscar special_minimum para este producto
                    special_min_rule = self.env['partner.product.special.minimum'].search([
                        ('partner_id', '=', partner.id),
                        ('product_id', '=', product.id),
                        ('company_id', '=', self.company_id.id or self.env.company.id)
                    ], limit=1)

                    if special_min_rule and special_min_rule.special_min_price > 0:
                        # Existe special_minimum: comparar con el cálculo
                        if base_subtotal < special_min_rule.special_min_price:
                            # Agregar/actualizar información en el nombre
                            updated_name = line.name
                            
                            # Remover info previa de precio unitario si existe
                            if "\nPrecio unitario:" in updated_name:
                                updated_name = updated_name.split("\nPrecio unitario:")[0]
                            
                            # Agregar información completa
                            updated_name += f"\nPrecio unitario: ${daily_rate:,.2f}"
                            if "Precio mínimo facturado" not in updated_name:
                                updated_name += f"\nPrecio mínimo facturado (${special_min_rule.special_min_price:,.2f})"
                            
                            line.with_context(check_move_validity=False).write({
                                'price_unit': special_min_rule.special_min_price,
                                'quantity': 1.0,
                                'name': updated_name
                            })
                            subtotal = special_min_rule.special_min_price
                        else:
                            # Actualizar precio unitario en nombre si no existe
                            updated_name = line.name
                            if "\nPrecio unitario:" not in updated_name:
                                updated_name += f"\nPrecio unitario: ${daily_rate:,.2f}"
                            
                            line.with_context(check_move_validity=False).write({
                                'price_unit': price_per_day,
                                'quantity': original_quantity,
                                'name': updated_name
                            })
                            subtotal = base_subtotal
                    else:
                        # No existe special_minimum: usar precio calculado
                        # Actualizar precio unitario en nombre si no existe
                        updated_name = line.name
                        if "\nPrecio unitario:" not in updated_name:
                            updated_name += f"\nPrecio unitario: ${daily_rate:,.2f}"
                        
                        line.with_context(check_move_validity=False).write({
                            'price_unit': price_per_day,
                            'quantity': original_quantity,
                            'name': updated_name
                        })
                        subtotal = base_subtotal

                # CASO 2: Partner NO tiene no_minimum_pricing (respeta mínimos normales)
                else:
                    effective_min_price = product.product_tmpl_id.min_price or 0.0

                    if effective_min_price > 0 and base_subtotal < effective_min_price:
                        # Agregar/actualizar información en el nombre
                        updated_name = line.name
                        
                        # Remover info previa de precio unitario si existe
                        if "\nPrecio unitario:" in updated_name:
                            updated_name = updated_name.split("\nPrecio unitario:")[0]
                        
                        # Agregar información completa
                        updated_name += f"\nPrecio unitario: ${daily_rate:,.2f}"
                        if "Precio mínimo facturado" not in updated_name:
                            updated_name += f"\nPrecio mínimo facturado (${effective_min_price:,.2f})"
                        
                        line.with_context(check_move_validity=False).write({
                            'price_unit': effective_min_price,
                            'quantity': 1.0,
                            'name': updated_name
                        })
                        subtotal = effective_min_price
                    else:
                        # Actualizar precio unitario en nombre si no existe
                        updated_name = line.name
                        if "\nPrecio unitario:" not in updated_name:
                            updated_name += f"\nPrecio unitario: ${daily_rate:,.2f}"
                        
                        line.with_context(check_move_validity=False).write({
                            'price_unit': price_per_day,
                            'quantity': original_quantity,
                            'name': updated_name
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
            
            # Forzar recálculo de impuestos en la factura después de modificar price_unit/quantity
            if line.move_id and line.move_id.state == 'draft':
                try:
                    line.move_id.with_context(check_move_validity=True)._recompute_dynamic_lines(recompute_all_taxes=True)
                except Exception:
                    pass  # Ignorar errores durante el recálculo

    @api.depends("quantity", "days_storage", "product_id", "calculate_custom")
    def _compute_price_unit(self):
        super()._compute_price_unit()
        for line in self:
            if not line.calculate_custom or not line.product_id:
                continue

            product = line.product_id
            if not product.product_tmpl_id.is_storage:
                continue

            partner = line.move_id.partner_id
            days = line.days_storage or 1
            
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

            price_per_day = daily_rate * days
            base_subtotal = line.quantity * price_per_day

            # CASO 1: Partner tiene no_minimum_pricing = True
            if partner and partner.no_minimum_pricing:
                # Buscar special_minimum
                special_min_rule = self.env['partner.product.special.minimum'].search([
                    ('partner_id', '=', partner.id),
                    ('product_id', '=', product.id),
                    ('company_id', '=', self.company_id.id or self.env.company.id)
                ], limit=1)

                if special_min_rule and special_min_rule.special_min_price > 0:
                    # Comparar con el cálculo
                    if base_subtotal < special_min_rule.special_min_price:
                        line.price_unit = special_min_rule.special_min_price
                    else:
                        line.price_unit = price_per_day
                else:
                    # No hay special_minimum: usar precio calculado
                    line.price_unit = price_per_day
                return

            # CASO 2: Partner NO tiene no_minimum_pricing
            else:
                # Usar min_price del producto
                effective_min_price = product.product_tmpl_id.min_price or 0.0

                if effective_min_price > 0 and base_subtotal < effective_min_price:
                    line.price_unit = effective_min_price
                else:
                    line.price_unit = price_per_day

    # ELIMINADO: _compute_price_subtotal - causaba problemas con el cálculo de IVA
    # El método interfería con la lógica interna de Odoo 16 para calcular impuestos

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
        
        # Actualizar days_invoiced en la task si la factura está posteada
        if res.task_id and res.move_id.state == 'posted':
            res.task_id._compute_days_storage_invoiced()
        
        return res

    def write(self, vals):
        # Guardar tasks afectadas antes del cambio
        tasks_to_update = self.env['project.task']
        if 'task_id' in vals or 'days_storage' in vals:
            tasks_to_update |= self.mapped('task_id')
            if 'task_id' in vals and vals['task_id']:
                tasks_to_update |= self.env['project.task'].browse(vals['task_id'])
        
        res = super().write(vals)
        
        # Solo recalcular precio si se modifican campos relevantes
        if any(field in vals for field in ['calculate_custom', 'quantity', 'days_storage']) and 'price_unit' not in vals:
            for line in self:
                if line.calculate_custom and line.product_id.product_tmpl_id.is_storage:
                    self._compute_price_unit()
        
        # Actualizar days_invoiced en las tasks afectadas
        if tasks_to_update:
            posted_tasks = tasks_to_update.filtered(
                lambda t: any(line.move_id.state == 'posted' for line in self if line.task_id == t)
            )
            if posted_tasks:
                posted_tasks._compute_days_storage_invoiced()
        
        return res
    
    def unlink(self):
        # Guardar tasks para actualizar después de eliminar
        tasks_to_update = self.mapped('task_id').filtered(
            lambda t: any(line.move_id.state == 'posted' for line in self if line.task_id == t)
        )
        
        res = super().unlink()
        
        # Actualizar days_invoiced después de eliminar
        if tasks_to_update:
            tasks_to_update._compute_days_storage_invoiced()
        
        return res