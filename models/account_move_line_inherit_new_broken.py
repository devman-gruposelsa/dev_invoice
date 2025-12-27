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

    # Campo para almacenar nuestro subtotal personalizado (solo lectura)
    custom_subtotal = fields.Float(
        string='Subtotal Personalizado',
        compute='_compute_custom_subtotal',
        store=True,
    )

    # =========================================================================
    # MÉTODO AUXILIAR: Obtiene precio mínimo efectivo
    # =========================================================================
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

    # =========================================================================
    # MÉTODO CENTRAL: Calcula precio unitario, cantidad y nombre
    # Retorna un diccionario con los valores calculados SIN escribir nada
    # =========================================================================
    def _calculate_custom_pricing(self):
        """
        Calcula el precio unitario, cantidad y nombre basado en la lógica de negocio.
        SOLO CALCULA, NO ESCRIBE.
        Retorna: dict con 'price_unit', 'quantity', 'name', 'subtotal'
        """
        self.ensure_one()

        result = {
            'price_unit': self.price_unit,
            'quantity': self.quantity,
            'name': self.name,
            'subtotal': self.price_unit * self.quantity,
            'changed': False,  # Indica si hubo cambios
        }

        if not self.calculate_custom or not self.product_id:
            return result

        product = self.product_id
        partner = self.move_id.partner_id
        days = self.days_storage or 1

        # =====================================================================
        # CASO: Producto de ALMACENAMIENTO (is_storage)
        # =====================================================================
        if product.product_tmpl_id.is_storage:
            # Obtener precio de la lista de precios
            pricelist = self.move_id.pricelist_id
            if pricelist:
                daily_rate = pricelist._get_product_price(
                    product,
                    quantity=1.0,
                    uom=product.uom_id,
                    date=self.move_id.date
                )
            else:
                daily_rate = product.list_price

            # Calcular subtotales y precio por día
            original_quantity = self.quantity
            price_per_day = daily_rate * days
            base_subtotal = original_quantity * price_per_day

            # Preparar nombre actualizado
            updated_name = self.name or ''

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
                        # Remover info previa de precio unitario si existe
                        if "\nPrecio unitario:" in updated_name:
                            updated_name = updated_name.split("\nPrecio unitario:")[0]

                        # Agregar información completa
                        updated_name += f"\nPrecio unitario: ${daily_rate:,.2f}"
                        if "Precio mínimo facturado" not in updated_name:
                            updated_name += f"\nPrecio mínimo facturado (${special_min_rule.special_min_price:,.2f})"

                        result['price_unit'] = special_min_rule.special_min_price
                        result['quantity'] = 1.0
                        result['name'] = updated_name
                        result['subtotal'] = special_min_rule.special_min_price
                        result['changed'] = True
                    else:
                        # Actualizar precio unitario en nombre si no existe
                        if "\nPrecio unitario:" not in updated_name:
                            updated_name += f"\nPrecio unitario: ${daily_rate:,.2f}"

                        result['price_unit'] = price_per_day
                        result['quantity'] = original_quantity
                        result['name'] = updated_name
                        result['subtotal'] = base_subtotal
                        result['changed'] = True
                else:
                    # No existe special_minimum: usar precio calculado
                    if "\nPrecio unitario:" not in updated_name:
                        updated_name += f"\nPrecio unitario: ${daily_rate:,.2f}"

                    result['price_unit'] = price_per_day
                    result['quantity'] = original_quantity
                    result['name'] = updated_name
                    result['subtotal'] = base_subtotal
                    result['changed'] = True

            # CASO 2: Partner NO tiene no_minimum_pricing (respeta mínimos normales)
            else:
                effective_min_price = product.product_tmpl_id.min_price or 0.0
                
                _logger.info(f"CASO 2 - Partner sin no_minimum_pricing")
                _logger.info(f"  base_subtotal={base_subtotal}, effective_min_price={effective_min_price}")
                _logger.info(f"  Condición: effective_min_price > 0 = {effective_min_price > 0}")
                _logger.info(f"  Condición: base_subtotal < effective_min_price = {base_subtotal < effective_min_price}")

                if effective_min_price > 0 and base_subtotal < effective_min_price:
                    # Remover info previa de precio unitario si existe
                    if "\nPrecio unitario:" in updated_name:
                        updated_name = updated_name.split("\nPrecio unitario:")[0]

                    # Agregar información completa
                    updated_name += f"\nPrecio unitario: ${daily_rate:,.2f}"
                    if "Precio mínimo facturado" not in updated_name:
                        updated_name += f"\nPrecio mínimo facturado (${effective_min_price:,.2f})"

                    result['price_unit'] = effective_min_price
                    result['quantity'] = 1.0
                    result['name'] = updated_name
                    result['subtotal'] = effective_min_price
                    result['changed'] = True
                else:
                    # Actualizar precio unitario en nombre si no existe
                    if "\nPrecio unitario:" not in updated_name:
                        updated_name += f"\nPrecio unitario: ${daily_rate:,.2f}"

                    result['price_unit'] = price_per_day
                    result['quantity'] = original_quantity
                    result['name'] = updated_name
                    result['subtotal'] = base_subtotal
                    result['changed'] = True

        # =====================================================================
        # CASO: Producto FOB (fob_total)
        # =====================================================================
        elif product.product_tmpl_id.fob_total:
            usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
            rate = 1.0
            if usd_currency:
                rate_data = usd_currency._get_rates(
                    self.env.company,
                    self.move_id.date or fields.Date.context_today(self)
                )
                rate = 1 / rate_data.get(usd_currency.id, 1.0)

            # Cálculo FOB
            fob_amount = (self.fob_total or 0.0) * rate * 0.001

            if partner and partner.no_minimum_pricing:
                result['price_unit'] = fob_amount
                result['quantity'] = self.quantity
                result['subtotal'] = fob_amount * self.quantity
                result['changed'] = True
            else:
                # Si no tiene no_minimum_pricing, verificar mínimo
                min_price = product.product_tmpl_id.min_price or 0.0
                if min_price > 0 and fob_amount < min_price:
                    result['price_unit'] = min_price
                    result['quantity'] = 1.0
                    result['subtotal'] = min_price
                    result['changed'] = True
                else:
                    result['price_unit'] = fob_amount
                    result['quantity'] = self.quantity
                    result['subtotal'] = fob_amount * self.quantity
                    result['changed'] = True

        return result

    # =========================================================================
    # MÉTODO PARA APLICAR EL PRICING CALCULADO
    # Este es el único lugar donde se escribe en la BD
    # =========================================================================
    def _apply_custom_pricing(self):
        """
        Aplica el pricing personalizado calculando y escribiendo los valores.
        Se llama desde create(), write() y onchange.
        """
        for line in self:
            if not line.calculate_custom or not line.product_id:
                continue

            # Evitar loops: si ya estamos aplicando pricing, salir
            if self.env.context.get('applying_custom_pricing'):
                continue

            pricing = line._calculate_custom_pricing()
            
            _logger.info(f"=== _apply_custom_pricing para línea {line.id} ===")
            _logger.info(f"Producto: {line.product_id.name}, is_storage: {line.product_id.product_tmpl_id.is_storage}")
            _logger.info(f"Valores actuales: price_unit={line.price_unit}, quantity={line.quantity}, days_storage={line.days_storage}")
            _logger.info(f"Valores calculados: price_unit={pricing['price_unit']}, quantity={pricing['quantity']}, subtotal={pricing['subtotal']}")
            _logger.info(f"Changed: {pricing['changed']}")

            if pricing['changed']:
                vals_to_write = {}

                if pricing['price_unit'] != line.price_unit:
                    vals_to_write['price_unit'] = pricing['price_unit']

                if pricing['quantity'] != line.quantity:
                    vals_to_write['quantity'] = pricing['quantity']

                if pricing['name'] != line.name:
                    vals_to_write['name'] = pricing['name']

                _logger.info(f"Vals to write: {vals_to_write}")
                
                if vals_to_write:
                    line.with_context(
                        check_move_validity=False,
                        applying_custom_pricing=True
                    ).write(vals_to_write)

    # =========================================================================
    # COMPUTE: Solo calcula el subtotal, NO escribe nada
    # =========================================================================
    @api.depends('quantity', 'price_unit', 'product_id', 'days_storage', 'calculate_custom')
    def _compute_custom_subtotal(self):
        """
        Calcula el subtotal personalizado.
        IMPORTANTE: Este método SOLO calcula, NO modifica price_unit ni quantity.
        """
        for line in self:
            if not line.calculate_custom or not line.product_id:
                line.custom_subtotal = 0.0
                continue

            # Simplemente calcular el subtotal basado en los valores actuales
            line.custom_subtotal = line.price_unit * line.quantity

    # =========================================================================
    # ONCHANGE: Permite actualización en tiempo real en el formulario
    # =========================================================================
    @api.onchange('product_id', 'quantity', 'days_storage', 'calculate_custom', 'fob_total')
    def _onchange_custom_pricing_fields(self):
        """
        Onchange para actualizar precio cuando el usuario modifica campos en el form.
        """
        if not self.calculate_custom or not self.product_id:
            return

        pricing = self._calculate_custom_pricing()

        if pricing['changed']:
            self.price_unit = pricing['price_unit']
            self.quantity = pricing['quantity']
            if pricing['name'] != self.name:
                self.name = pricing['name']

    # =========================================================================
    # CREATE: Aplica pricing después de crear
    # =========================================================================
    @api.model_create_multi
    def create(self, vals_list):
        # Crear los registros primero
        lines = super().create(vals_list)

        # Aplicar pricing personalizado a las líneas que lo requieran
        # NOTA: Si se pasa skip_custom_pricing=True en el contexto, no se recalcula
        # Esto es útil cuando el precio ya fue calculado correctamente (ej: action_create_outcome_invoice)
        if not self.env.context.get('skip_custom_pricing'):
            lines_to_process = lines.filtered(lambda l: l.calculate_custom and l.product_id)
            if lines_to_process:
                lines_to_process._apply_custom_pricing()

        # Actualizar days_invoiced en la task si la factura está posteada
        for line in lines:
            if line.task_id and line.move_id.state == 'posted':
                line.task_id._compute_days_storage_invoiced()

        return lines

    # =========================================================================
    # WRITE: Aplica pricing cuando se modifican campos relevantes
    # =========================================================================
    def write(self, vals):
        # Evitar loops
        if self.env.context.get('applying_custom_pricing'):
            return super().write(vals)

        # Guardar tasks afectadas antes del cambio
        tasks_to_update = self.env['project.task']
        if 'task_id' in vals or 'days_storage' in vals:
            tasks_to_update |= self.mapped('task_id')
            if 'task_id' in vals and vals['task_id']:
                tasks_to_update |= self.env['project.task'].browse(vals['task_id'])

        res = super().write(vals)

        # Campos que disparan recálculo de pricing
        pricing_trigger_fields = ['calculate_custom', 'quantity', 'days_storage', 'fob_total', 'product_id']

        # Solo recalcular si se modifican campos relevantes Y no se está escribiendo price_unit directamente
        if any(field in vals for field in pricing_trigger_fields) and 'price_unit' not in vals:
            lines_to_process = self.filtered(lambda l: l.calculate_custom and l.product_id)
            if lines_to_process:
                lines_to_process._apply_custom_pricing()

        # Actualizar days_invoiced en las tasks afectadas
        if tasks_to_update:
            posted_tasks = tasks_to_update.filtered(
                lambda t: any(line.move_id.state == 'posted' for line in self if line.task_id == t)
            )
            if posted_tasks:
                posted_tasks._compute_days_storage_invoiced()

        return res

    # =========================================================================
    # UNLINK: Actualiza tasks al eliminar líneas
    # =========================================================================
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
