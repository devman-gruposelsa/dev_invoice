from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date
import calendar
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def check_and_update_order_status(self):
        for order in self:
            if order.state == 'sale':  # Verificar si el estado es 'pedido de venta'
                all_tasks_completed = True
                if order.task_ids:
                    for task in order.task_ids:
                        # Verificar si hay stock disponible para el lote con el mismo nombre que la tarea
                        lot_stock_qty = self.env['stock.quant'].search([
                            ('lot_id.name', '=', task.name),
                            ('quantity', '>', 0)
                        ])
                        if lot_stock_qty:
                            all_tasks_completed = False
                            break
                    if all_tasks_completed:
                        for task in order.task_ids:
                            task.write({'full_transit': True})
                    else:
                        for task in order.task_ids:
                            task.write({'full_transit': False})
            elif order.state in ['cancel', 'draft']:  # Si el pedido es cancelado o eliminado
                for task in order.task_ids:
                    task.write({'full_transit': False})

    #@api.model
    def write(self, vals):
        res = super(SaleOrder, self).write(vals)
        self.check_and_update_order_status()
        return res

    def unlink(self):
        for order in self:
            if order.state in ['cancel', 'draft']:
                for task in order.task_ids:
                    task.write({'full_transit': False})
        return super(SaleOrder, self).unlink()
    
    def action_create_outcome_invoice(self):
        _logger.info("Generando facturas de egreso...")
        return self._create_invoice('outcome_invoice_pack')

    def _create_invoice(self, product_pack_field):
        account_move_obj = self.env['account.move']
        # Usar contexto skip_custom_pricing para evitar recálculo de precios
        # ya que este método calcula los precios correctamente
        account_move_line_obj = self.env['account.move.line'].with_context(skip_custom_pricing=True)

        for order in self:
            # Validación de egreso_completo en las tareas asociadas
            for task in order.task_ids:
                if task.egreso_completo:
                    raise ValidationError(f"Este tránsito no se puede facturar porque está en 'Egreso Completo'. (Tarea: {task.name})")

            # Fecha de facturación (hoy)
            invoice_date = date.today()
            
            # Obtener tipo de cambio USD (inverse_rate = precio de 1 USD en ARS)
            usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
            inverse_rate = 1.0
            if usd_currency:
                inverse_rate = usd_currency.inverse_rate or 1.0
            
            _logger.info(f"[INVOICE] Tipo de cambio USD inverse_rate: {inverse_rate}")
            
            # =====================================================================
            # OBTENER TOTALES DESDE LAS LÍNEAS DEL SALE.ORDER AGRUPADOS POR TASK_ID
            # Si m3_total está en 0, calculamos desde qty_delivered * product.volume
            # =====================================================================
            task_totals = {}
            for line in order.order_line:
                if line.task_id:
                    task_id = line.task_id.id
                    if task_id not in task_totals:
                        task_totals[task_id] = {
                            'task': line.task_id,
                            'fob_total': 0.0,
                            'm3_total': 0.0,
                        }
                    # FOB total
                    task_totals[task_id]['fob_total'] += line.fob_total or 0.0
                    
                    # M3 total - si está en 0, calcular desde qty_delivered * volume
                    line_m3 = line.m3_total or 0.0
                    if line_m3 == 0.0 and line.product_id:
                        # Calcular M3 desde cantidad entregada * volumen del producto
                        qty = line.qty_delivered or line.product_uom_qty or 0.0
                        volume = line.product_id.volume or 0.0
                        line_m3 = qty * volume
                        _logger.info(f"[M3_CALC] Línea {line.id}: qty={qty} * volume={volume} = {line_m3:.6f}")
                    
                    task_totals[task_id]['m3_total'] += line_m3
            
            # Log de totales por task
            for task_id, data in task_totals.items():
                _logger.info(f"[INVOICE] Task {data['task'].name}: FOB={data['fob_total']:.2f}, M3={data['m3_total']:.6f}")
            
            # Calcular totales globales del pedido (sumando todas las tasks)
            order_fob_total = sum(data['fob_total'] for data in task_totals.values())
            order_m3_total = sum(data['m3_total'] for data in task_totals.values())
            
            _logger.info(f"[INVOICE] Pedido {order.name}: FOB Total={order_fob_total:.2f}, M3 Total={order_m3_total:.6f}")
            
            # Crear la factura vinculada al sale order
            invoice = account_move_obj.create({
                'partner_id': order.partner_id.id,
                'move_type': 'out_invoice',  # Factura de cliente
                'invoice_origin': order.name,
                'invoice_date': invoice_date,
            })
            _logger.info(f"Factura creada con ID: {invoice.id} para el pedido {order.name} (ID: {order.id})")

            # Determinar si alguna tarea es IMO para filtrar productos
            any_task_imo = any(task.is_imo for task in order.task_ids if hasattr(task, 'is_imo'))
            
            # Buscar productos con el filtro IMO/General correcto
            products = self._get_outcome_products(product_pack_field, any_task_imo)
            if not products:
                raise ValidationError(f'No hay productos configurados para el paquete {product_pack_field}')

            # Obtener nombres de tareas para la descripción
            task_names = ', '.join(order.task_ids.mapped('name'))
            first_task = order.task_ids[0] if order.task_ids else False

            for product in products:
                # --- PRODUCTO FOB ---
                # UNA SOLA LÍNEA con la suma de todos los FOB de todas las tasks
                if product.product_tmpl_id.fob_total:
                    if order_fob_total > 0:
                        # Calcular price_unit para FOB: fob_total * inverse_rate * 0.001
                        calculated_fob_price = order_fob_total * inverse_rate * 0.001
                        
                        _logger.info(f"[FOB] Total: FOB={order_fob_total:.2f} * Rate={inverse_rate:.2f} * 0.001 = {calculated_fob_price:.2f}")
                        
                        # Aplicar lógica de precios mínimos
                        final_price_unit = calculated_fob_price
                        final_quantity = 1
                        minimum_applied = False
                        minimum_amount = 0.0
                        
                        _logger.info(f"[FOB-MIN] === INICIO DEBUG MINIMO ===")
                        _logger.info(f"[FOB-MIN] Partner: {order.partner_id.name} (ID: {order.partner_id.id})")
                        _logger.info(f"[FOB-MIN] no_minimum_pricing: {order.partner_id.no_minimum_pricing}")
                        _logger.info(f"[FOB-MIN] Producto: {product.name} (ID: {product.id})")
                        _logger.info(f"[FOB-MIN] Precio calculado FOB: {calculated_fob_price:.2f}")
                        
                        # CASO 1: Partner tiene no_minimum_pricing = True
                        # Buscar mínimo especial en partner.product.special.minimum
                        # Si encuentra, comparar con ese. Si no encuentra, usar precio calculado (sin mínimo)
                        if order.partner_id.no_minimum_pricing:
                            _logger.info(f"[FOB-MIN] CASO 1: no_minimum_pricing=True, buscando special_minimum...")
                            special_minimum = self.env['partner.product.special.minimum'].search([
                                ('partner_id', '=', order.partner_id.id),
                                ('product_id', '=', product.id),
                                ('company_id', '=', self.env.company.id)
                            ], limit=1)
                            
                            if special_minimum:
                                _logger.info(f"[FOB-MIN] Special minimum encontrado: {special_minimum.special_min_price}")
                                if special_minimum.special_min_price > 0 and calculated_fob_price < special_minimum.special_min_price:
                                    final_price_unit = special_minimum.special_min_price
                                    minimum_applied = True
                                    minimum_amount = special_minimum.special_min_price
                                    _logger.info(f"[FOB-MIN] APLICANDO mínimo especial: {final_price_unit}")
                                else:
                                    _logger.info(f"[FOB-MIN] Precio calculado ({calculated_fob_price:.2f}) >= mínimo especial ({special_minimum.special_min_price}), NO se aplica")
                            else:
                                _logger.info(f"[FOB-MIN] NO hay special_minimum para este producto, usando precio calculado sin mínimo")
                        
                        # CASO 2: Partner NO tiene no_minimum_pricing (False)
                        # Comparar con el min_price del producto
                        else:
                            _logger.info(f"[FOB-MIN] CASO 2: no_minimum_pricing=False, usando min_price del producto...")
                            min_price = product.product_tmpl_id.min_price or 0.0
                            _logger.info(f"[FOB-MIN] min_price del producto: {min_price}")
                            if min_price > 0 and calculated_fob_price < min_price:
                                final_price_unit = min_price
                                minimum_applied = True
                                minimum_amount = min_price
                                _logger.info(f"[FOB-MIN] APLICANDO mínimo del producto: {final_price_unit}")
                            else:
                                _logger.info(f"[FOB-MIN] Precio calculado ({calculated_fob_price:.2f}) >= min_price ({min_price}) o min_price=0, NO se aplica")
                        
                        _logger.info(f"[FOB-MIN] === FIN DEBUG: final_price_unit={final_price_unit}, minimum_applied={minimum_applied} ===")
                        
                        # Construir nombre con TODAS las tasks
                        name = f"{product.name} - {task_names} - FOB total: {order_fob_total:,.2f} - USD: {inverse_rate:,.2f}"
                        if minimum_applied:
                            name += f"\nPrecio mínimo facturado (${minimum_amount:,.2f})"
                        
                        account_move_line_obj.create({
                            'move_id': invoice.id,
                            'product_id': product.id,
                            'quantity': final_quantity,
                            'calculate_custom': True,
                            'fob_total': order_fob_total,
                            'price_unit': final_price_unit,
                            'price_locked': True,
                            'name': name,
                            'account_id': self._get_income_account(product, invoice),
                            'task_id': first_task.id if first_task else False,
                        })
                        _logger.info(f"Línea FOB creada: {product.name} - FOB Total: {order_fob_total:.2f} - Price: {final_price_unit:.2f}")
                    else:
                        _logger.info(f"Producto FOB {product.name} omitido porque fob_total del pedido es 0")
                
                # --- PRODUCTO ALMACENAMIENTO ---
                # Una línea por cada task
                elif product.product_tmpl_id.is_storage:
                    # Calcular días de almacenamiento: desde inicio del mes hasta fecha de ENTREGA del pedido (inclusive)
                    # Usar commitment_date del sale.order si existe, sino usar fecha de facturación
                    delivery_date = order.commitment_date.date() if order.commitment_date else invoice_date
                    first_day_of_month = delivery_date.replace(day=1)
                    storage_days = (delivery_date - first_day_of_month).days + 1
                    _logger.info(f"Días de almacenamiento calculados: desde {first_day_of_month} hasta {delivery_date} (fecha entrega) = {storage_days} días")

                    # Crear una línea de factura por cada task
                    for task_id, task_data in task_totals.items():
                        task = task_data['task']
                        m3_quantity = task_data['m3_total'] if task_data['m3_total'] > 0 else 1.0
                        
                        _logger.info(f"[STORAGE] Task {task.name}: M3={m3_quantity:.6f}")
                        
                        # Obtener precio de lista de precios (precio diario por m3)
                        # Usar la pricelist del sale.order o del partner
                        pricelist = order.pricelist_id or invoice.partner_id.property_product_pricelist
                        daily_rate = product.product_tmpl_id.list_price
                        
                        _logger.info(f"[STORAGE] Pricelist: {pricelist.name if pricelist else 'None'}, Product list_price: {daily_rate}")
                        
                        if pricelist:
                            try:
                                partner_for_pricelist = invoice.partner_id.commercial_partner_id or invoice.partner_id
                                # En Odoo 16, el método correcto es _get_product_price
                                daily_rate = pricelist._get_product_price(
                                    product,
                                    quantity=m3_quantity if m3_quantity > 0 else 1.0,
                                    uom=product.uom_id,
                                    date=delivery_date,
                                )
                                _logger.info(f"[STORAGE] Precio de pricelist: ${daily_rate:.2f}")
                            except Exception as e:
                                _logger.error(f"Error obteniendo precio de lista: {e}")
                                daily_rate = product.product_tmpl_id.list_price

                        # =====================================================================
                        # CÁLCULO DE ALMACENAMIENTO:
                        # - Cantidad = M3 totales
                        # - Precio unitario = daily_rate * días
                        # - Subtotal = Cantidad * Precio unitario = M3 * daily_rate * días
                        # =====================================================================
                        price_unit_storage = daily_rate * storage_days
                        calculated_total = m3_quantity * price_unit_storage
                        
                        _logger.info(f"[STORAGE] Cálculo: {m3_quantity:.2f} m3 * ${daily_rate:.2f}/día * {storage_days} días = ${calculated_total:.2f}")
                        
                        # Verificar mínimos según la lógica de facturación
                        # Usar order.partner_id para verificar mínimos (es el partner principal/compañía)
                        final_quantity = m3_quantity
                        final_price_unit = price_unit_storage
                        minimum_applied = False
                        minimum_amount = 0.0

                        # CASO 1: Partner tiene no_minimum_pricing = True
                        if order.partner_id.no_minimum_pricing:
                            special_minimum = self.env['partner.product.special.minimum'].search([
                                ('partner_id', '=', order.partner_id.id),
                                ('product_id', '=', product.id),
                                ('company_id', '=', self.env.company.id)
                            ], limit=1)
                            
                            if special_minimum and special_minimum.special_min_price > 0:
                                if calculated_total < special_minimum.special_min_price:
                                    final_quantity = 1
                                    final_price_unit = special_minimum.special_min_price
                                    minimum_applied = True
                                    minimum_amount = special_minimum.special_min_price
                        # CASO 2: Partner NO tiene no_minimum_pricing
                        else:
                            min_price = product.product_tmpl_id.min_price or 0.0
                            if min_price > 0 and calculated_total < min_price:
                                final_quantity = 1
                                final_price_unit = min_price
                                minimum_applied = True
                                minimum_amount = min_price

                        # Construir nombre/descripción
                        name = f"{product.name} - {task.name} - {m3_quantity:.2f} m3 - {storage_days} días"
                        name += f"\nPrecio unitario: ${daily_rate:,.2f}"
                        if minimum_applied:
                            name += f"\nPrecio mínimo facturado (${minimum_amount:,.2f})"

                        account_move_line_obj.create({
                            'move_id': invoice.id,
                            'product_id': product.id,
                            'quantity': final_quantity,
                            'days_storage': storage_days,
                            'calculate_custom': True,
                            'price_unit': final_price_unit,
                            'price_locked': True,
                            'name': name,
                            'account_id': self._get_income_account(product, invoice),
                            'task_id': task.id,
                        })
                        _logger.info(f"Línea almacenamiento: {task.name} - Qty:{final_quantity:.2f} - Price:{final_price_unit:.2f} - Subtotal:{final_quantity * final_price_unit:.2f}")

                # --- PRODUCTO ONE_LINE_INVOICE ---
                elif product.product_tmpl_id.one_line_invoice:
                    # Solo una línea con quantity=1, independiente del número de tareas
                    account_move_line_obj.create({
                        'move_id': invoice.id,
                        'product_id': product.id,
                        'quantity': 1,
                        'price_unit': product.lst_price,
                        'name': f"{product.name} - {task_names}",
                        'account_id': self._get_income_account(product, invoice),
                        'task_id': first_task.id if first_task else False,
                    })
                    _logger.info(f"Línea one_line_invoice creada: {product.name} - {task_names}")
                
                # --- PRODUCTO NORMAL ---
                else:
                    account_move_line_obj.create({
                        'move_id': invoice.id,
                        'product_id': product.id,
                        'quantity': 1,
                        'price_unit': product.lst_price,
                        'name': f"{product.name} - {task_names}",
                        'account_id': self._get_income_account(product, invoice),
                        'task_id': first_task.id if first_task else False,
                    })
                    _logger.info(f"Línea normal creada: {product.name} - {task_names}")
            
            try:
                invoice.button_update_prices_from_pricelist()
            except Exception as e:
                _logger.error(f"Error al actualizar precios para la factura {invoice.id}: {str(e)}")

            # Validar y agregar productos para tareas con full_transit
            full_transit_tasks = order.task_ids.filtered(lambda task: task.full_transit)
            if full_transit_tasks:
                product_full_transit = self.env['product.product'].search([('product_tmpl_id.product_full_transit', '=', True)], limit=1)
                if not product_full_transit:
                    raise ValidationError('No hay productos configurados con el campo product_full_transit en True.')

                task_names_full = '-'.join(full_transit_tasks.mapped('name'))
                invoice_line_vals = {
                    'move_id': invoice.id,
                    'product_id': product_full_transit.id,
                    'quantity': 1,
                    'price_unit': product_full_transit.lst_price,
                    'name': f"{product_full_transit.name} - {task_names_full}",
                    'account_id': self._get_income_account(product_full_transit, invoice),
                    'task_id': full_transit_tasks[0].id,
                }
                account_move_line_obj.create(invoice_line_vals)
                _logger.info(f"Línea de factura creada para tareas con full_transit: {task_names_full}")

            # Vincular la factura al sale.order usando sale_line_ids en la primera línea del pedido
            # Esto permite que la factura aparezca en el contador de facturas del pedido
            if order.order_line:
                first_order_line = order.order_line.filtered(lambda l: not l.display_type)[:1]
                if first_order_line and invoice.invoice_line_ids:
                    first_invoice_line = invoice.invoice_line_ids[:1]
                    try:
                        first_invoice_line.write({'sale_line_ids': [(4, first_order_line.id)]})
                        _logger.info(f"Factura {invoice.id} vinculada al pedido {order.name}")
                    except Exception as e:
                        _logger.warning(f"No se pudo vincular la factura al pedido: {e}")

            # Devolver una acción para abrir la factura recién creada
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'view_mode': 'form',
                'res_id': invoice.id,
                'target': 'current',
            }
    
    def _get_outcome_products(self, product_pack_field, is_imo):
        """Helper method to get products based on pack field and IMO status"""
        base_domain = [('product_tmpl_id.' + product_pack_field, '=', True)]
        
        if is_imo:
            # Si es IMO, traer productos IMO y generales
            imo_domain = ['|', 
                ('product_tmpl_id.is_general', '=', True), 
                ('product_tmpl_id.is_imo', '=', True)
            ]
        else:
            # Si no es IMO, traer productos generales y los que NO son solo IMO
            imo_domain = ['|', 
                ('product_tmpl_id.is_general', '=', True), 
                '&', 
                    ('product_tmpl_id.is_general', '=', False), 
                    ('product_tmpl_id.is_imo', '=', False)
            ]
        
        return self.env['product.product'].search(base_domain + imo_domain)

    def _get_income_account(self, product, invoice):
        """Helper method to get the income account for a product"""
        # Primero intentar obtener la cuenta del producto
        if product.property_account_income_id:
            return product.property_account_income_id.id
        # Luego de la categoría del producto
        if product.categ_id.property_account_income_categ_id:
            return product.categ_id.property_account_income_categ_id.id
        # Finalmente del diario de la factura
        if invoice.journal_id.default_account_id:
            return invoice.journal_id.default_account_id.id
        return False

    def _get_picking_totals_by_task(self, order):
        """
        Obtiene los totales de fob_total y m3_total agrupados por task_id
        desde los pickings (stock.picking) asociados al sale.order.
        
        Esto es más confiable que tomar los valores desde el sale.order.line
        porque los pickings tienen los valores calculados desde los lotes reales.
        
        Returns:
            dict: {task_id: {'task': project.task, 'fob_total': float, 'm3_total': float}}
        """
        task_totals = {}
        
        # Obtener pickings salientes (outgoing) del sale.order
        outgoing_pickings = order.picking_ids.filtered(
            lambda p: p.picking_type_id.code == 'outgoing' and p.state not in ('draft', 'cancel')
        )
        
        _logger.info(f"[PICKING_TOTALS] Sale Order {order.name}: {len(outgoing_pickings)} pickings outgoing encontrados")
        
        # Log de todos los pickings disponibles para debug
        _logger.info(f"[PICKING_TOTALS] Todos los pickings del order: {[(p.name, p.picking_type_id.code, p.state) for p in order.picking_ids]}")
        
        for picking in outgoing_pickings:
            _logger.info(f"[PICKING_TOTALS] Procesando picking {picking.name}, moves: {len(picking.move_ids)}")
            
            # Iterar sobre los stock.move del picking
            for move in picking.move_ids:
                # Obtener el task_id desde sale_line_id
                task = move.sale_line_id.task_id if move.sale_line_id and move.sale_line_id.task_id else False
                
                if not task:
                    # Si no hay task en la línea de venta, intentar desde el picking
                    task = picking.task_id if hasattr(picking, 'task_id') and picking.task_id else False
                
                if not task:
                    # Intentar obtener la task desde el lot_id del move_line
                    for ml in move.move_line_ids:
                        if ml.lot_id and ml.lot_id.name:
                            task_from_lot = self.env['project.task'].search([('name', '=', ml.lot_id.name)], limit=1)
                            if task_from_lot:
                                task = task_from_lot
                                break
                
                if not task:
                    _logger.warning(f"[PICKING_TOTALS] Move {move.id} (Product: {move.product_id.name}) sin task_id asociado, omitiendo")
                    continue
                
                task_id = task.id
                
                if task_id not in task_totals:
                    task_totals[task_id] = {
                        'task': task,
                        'fob_total': 0.0,
                        'm3_total': 0.0,
                    }
                
                # Sumar los totales desde las move_line_ids (tienen fob y m3 desde el lote)
                for move_line in move.move_line_ids:
                    # total_fob y total_m3 están calculados en stock.move.line desde el lot_id
                    line_fob = getattr(move_line, 'total_fob', 0.0) or 0.0
                    line_m3 = getattr(move_line, 'total_m3', 0.0) or 0.0
                    
                    # Si no hay total_fob/total_m3, calcular desde el lote
                    if line_fob == 0.0 and move_line.lot_id:
                        unit_fob = getattr(move_line.lot_id, 'unit_fob', 0.0) or 0.0
                        qty = move_line.qty_done or move_line.reserved_qty or 0.0
                        line_fob = unit_fob * qty
                    
                    if line_m3 == 0.0 and move_line.lot_id:
                        unit_m3 = getattr(move_line.lot_id, 'unit_m3', 0.0) or 0.0
                        qty = move_line.qty_done or move_line.reserved_qty or 0.0
                        line_m3 = unit_m3 * qty
                    
                    task_totals[task_id]['fob_total'] += line_fob
                    task_totals[task_id]['m3_total'] += line_m3
                    
                    _logger.info(f"[PICKING_TOTALS] Move Line {move_line.id} (Lot: {move_line.lot_id.name if move_line.lot_id else 'N/A'}, Qty: {move_line.qty_done}): FOB={line_fob:.2f}, M3={line_m3:.6f}")
        
        # Si no se encontraron datos en los pickings, intentar desde las líneas del sale.order
        if not task_totals:
            _logger.warning(f"[PICKING_TOTALS] No se encontraron datos en pickings, intentando desde order.order_line")
            for line in order.order_line:
                if line.task_id:
                    task_id = line.task_id.id
                    if task_id not in task_totals:
                        task_totals[task_id] = {
                            'task': line.task_id,
                            'fob_total': 0.0,
                            'm3_total': 0.0,
                        }
                    task_totals[task_id]['fob_total'] += line.fob_total or 0.0
                    task_totals[task_id]['m3_total'] += line.m3_total or 0.0
                    _logger.info(f"[PICKING_TOTALS] Order Line: Task={line.task_id.name}, FOB={line.fob_total}, M3={line.m3_total}")
        
        # Log resumen
        _logger.info(f"[PICKING_TOTALS] === RESUMEN ===")
        for task_id, data in task_totals.items():
            _logger.info(f"[PICKING_TOTALS] Task {data['task'].name}: FOB Total={data['fob_total']:.2f}, M3 Total={data['m3_total']:.6f}")
        
        if not task_totals:
            _logger.error(f"[PICKING_TOTALS] No se encontraron datos de tareas para el pedido {order.name}")
        
        return task_totals
