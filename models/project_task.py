# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import timedelta
import calendar

_logger = logging.getLogger(__name__)


class ProjectTask(models.Model):
    _inherit = 'project.task'

    transit_total_cost = fields.Float(
        string='Costo total del transito',
        compute='_compute_transit_total_cost',
        store=True,
        help="Sum of the untaxed amounts of all filtered invoices associated with this task."
    )

    date_next_billing = fields.Date(string="Fecha de proxima facturación mensual", help="Corresponde a la fecha en la cual desea que se realice la facturación mensual, la misma aumentara en dias")
    
    days_invoiced = fields.Integer(string="Días de Almacenamiento Facturado", compute="_compute_days_storage_invoiced", store=True, help="Días de almacenamiento facturados en las líneas de factura.", tracking=True)

    days_to_invoiced = fields.Integer(string="Días de Almacenamiento a Facturar", compute="_compute_days_storage_to_invoiced", store=True, help="Días de almacenamiento a facturar.")

    full_transit = fields.Boolean(string="Tránsito Completo", help="Indica si el tránsito está completo y listo para facturar.", store=True)

    move_lines_ids = fields.Many2many('account.move.line', compute="_compute_move_line_ids", string="Líneas de Factura", help="Líneas de factura asociadas a esta tarea.", store=False)


    @api.depends('name', 'invoice_ids_filtered')
    def _compute_move_line_ids(self):
        for task in self:
            move_lines = self.env['account.move.line'].search([
                ('task_id', '=', task.id),  # Filtra por el id de la tarea
            ])
            task.move_lines_ids = move_lines

    def costo_total_transito(self):
        for rec in self:
            rec._compute_transit_total_cost()

    @api.depends('move_lines_ids')
    def _compute_transit_total_cost(self):
        for rec in self:
            _logger.info(f"Calculando costo total de tránsito para tarea: {rec.id}")
            
            # Búsqueda optimizada: incluimos facturas y notas de crédito
            moves = self.env['account.move'].search([
                ('task_id', 'in', [rec.id]),
                ('move_type', 'in', ['out_invoice', 'out_refund']),  # Facturas y notas de crédito
                ('state', 'not in', ['draft', 'cancel'])
            ])
            
            if moves:
                # Para notas de crédito el amount es negativo, se suma automáticamente
                rec.transit_total_cost = sum(moves.mapped('amount_untaxed_signed'))
                _logger.info(
                    f"Tarea: {rec.id} | "
                    f"Documentos encontrados: {len(moves)} | "
                    f"Total: {rec.transit_total_cost} | "
                    f"IDs: {moves.ids}"
                )
            else:
                rec.transit_total_cost = 0.0
                _logger.info(f"Tarea: {rec.id} | No se encontraron documentos relacionados")
    
    @api.depends('move_lines_ids.days_storage', 'move_lines_ids.move_id.state', 'days_storage')
    def _compute_days_storage_invoiced(self):
        for task in self:
            posted_lines = task.move_lines_ids.filtered(lambda line: line.move_id.state == 'posted')
            task.days_invoiced = sum(posted_lines.mapped('days_storage') or [0])

    @api.depends('days_storage', 'days_invoiced')
    def _compute_days_storage_to_invoiced(self):
        for task in self:
            task.days_to_invoiced = max(0, (task.days_storage or 0) - (task.days_invoiced or 0))

    def action_open_days_invoiced_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Modificar Días Facturados',
            'res_model': 'project.task.days.invoiced.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_task_id': self.id},
        }

    def action_open_fecha_ingreso_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Modificar Fecha de Ingreso',
            'res_model': 'project.task.fecha.ingreso.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_task_id': self.id},
        }


    def _create_invoice(self, product_pack_field):
        account_move_obj = self.env['account.move']
        account_move_line_obj = self.env['account.move.line']

        for task in self:
            # Validación de egreso_completo
            if task.egreso_completo:
                raise ValidationError(f"Este tránsito no se puede facturar porque está en 'Egreso Completo'. (Tarea: {task.name})")

            # Validar que la fecha de ingreso esté definida
            if not task.fecha_ingreso:
                raise ValidationError(f"La tarea {task.name} no tiene definida la fecha de ingreso.")

            # Buscar productos asociados al campo específico
            base_domain = [('product_tmpl_id.' + product_pack_field, '=', True)]
            imo_general_domain = ['|', ('product_tmpl_id.is_general', '=', True), '&', ('product_tmpl_id.is_general', '=', False), ('is_imo', '=', task.is_imo)]
            domain = base_domain + imo_general_domain

            products = self.env['product.product'].search(domain)
            if not products:
                raise ValidationError('No hay productos configurados con el paquete solicitado.')

            # Preparar el contenido del campo narration
            if product_pack_field == 'income_invoice_pack':
                narration = (
                    "NOTA DE FACTURA DE INGRESO<br/>"
                    f"ZFI: {task.zfi or ''}<br/>"
                    f"Fecha de Ingreso: {task.fecha_ingreso.strftime('%d-%m-%Y') if task.fecha_ingreso else ''}<br/>"
                    f"Tipo de Carga: {task.load_type or ''}<br/><br/>"
                    "Banco Santander<br/>"
                    "CBU: 0720429020000000055554<br/>"
                    "Banco Credicoop<br/>"
                    "CBU: 1910246555024600234278<br/><br/>"
                    "BAJA EN IIBB CABA - BS AS DESDE 31/08/2024"
                )
            elif product_pack_field == 'outcome_invoice_pack':
                narration = (
                    "NOTA DE FACTURA DE EGRESO<br/>"
                    f"ZFE: {task.zfe or ''}<br/>"
                    f"Fecha de Retiro: {fields.Date.today().strftime('%d-%m-%Y')}<br/><br/>"
                    "Banco Santander<br/>"
                    "CBU: 0720429020000000055554<br/>"
                    "Banco Credicoop<br/>"
                    "CBU: 1910246555024600234278<br/><br/>"
                    "BAJA EN IIBB CABA - BS AS DESDE 31/08/2024"
                )
            else:
                narration = ""

            # Crear la factura
            invoice = account_move_obj.create({
                'partner_id': task.partner_id.id,
                'move_type': 'out_invoice',  # Factura de cliente
                'invoice_origin': task.name,
                'invoice_date': fields.Date.today(),  # Fecha de la factura
                'narration': narration,  # Agregar la narración
            })
            _logger.info(f"Factura creada con ID: {invoice.id} para la tarea {task.name} (ID: {task.id})")

            # Obtener la tasa de cambio de USD
            usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
            if not usd_currency:
                raise ValidationError("No se encontró la divisa USD en el sistema.")

            rate = usd_currency.rate  # Tasa de cambio actual de USD
            _logger.info(f"Tasa de cambio USD: {rate}")

            if not task.fecha_ingreso:
                raise ValidationError(f"La tarea {task.name} no tiene definida la fecha de ingreso.")

            # Validar si la fecha de la factura está en el mismo mes que la fecha_ingreso
            factura_mes = invoice.invoice_date.month
            factura_anio = invoice.invoice_date.year
            ingreso_mes = task.fecha_ingreso.month
            ingreso_anio = task.fecha_ingreso.year

            # Agregar líneas de factura
            for product in products:
                # Verificar si el product.template tiene fob_total como True
                if product.product_tmpl_id.fob_total:
                    if factura_mes != ingreso_mes and factura_anio != ingreso_anio:
                        _logger.info(f"Producto {product.name} omitido porque la fecha de factura está en distinto mes que la fecha de ingreso.")
                        continue  # Saltar este producto
                    elif factura_anio == ingreso_anio and factura_mes == ingreso_mes:
                        # Calcular el quantity como total_fob * rate * 0.001 si el mes/año de la factura es posterior
                        quantity = task.total_fob * rate * 0.001
                        calculate_custom = True
                        product_name = f"{task.name} - Fob total:{task.total_fob} - USD:{rate}"
                        _logger.info(f"Tipo de cambio {rate} - Total FOB {task.total_fob}")
                    else:
                        # Si el mes/año de la factura es anterior, no agregar el producto
                        _logger.info(f"Producto {product.name} omitido porque la fecha de factura es anterior a la fecha de ingreso.")
                        continue
                else:
                    # Para productos sin fob_total, usar valores predeterminados
                    quantity = 1
                    calculate_custom = False
                    product_name = product.name

                line = account_move_line_obj.create({
                    'move_id': invoice.id,
                    'product_id': product.id,
                    'quantity': quantity,
                    'calculate_custom': calculate_custom,
                    'price_unit': product.lst_price,
                    'name': product_name,
                    'account_id': product.categ_id.property_account_income_categ_id.id,
                    'task_id': task.id,  # Relación con la tarea
                })
                _logger.info(f"Línea de factura creada con ID: {line.id}, relacionada con la tarea {task.name} (ID: {task.id})")
            
            try:
                invoice.button_update_prices_from_pricelist()
            except Exception as e:
                _logger.error(f"Error al actualizar precios para la factura {invoice.id}: {str(e)}")

            # Abrir la factura recién creada
            return {
                'type': 'ir.actions.act_window',
                'name': 'Factura',
                'res_model': 'account.move',
                'view_mode': 'form',
                'res_id': invoice.id,
                'target': 'current',
            }

    def action_create_income_invoice(self):
        _logger.info("Generando facturas de ingreso...")
        self._create_invoice('income_invoice_pack')

    def action_create_outcome_invoice(self):
        _logger.info("Generando facturas de egreso...")
        self._create_invoice('outcome_invoice_pack')

    def action_create_storage_invoice(self):
        account_move_obj = self.env['account.move']
        account_move_line_obj = self.env['account.move.line']

        for task in self:
            # Validación de egreso_completo
            if task.egreso_completo:
                raise ValidationError(f"Este tránsito no se puede facturar porque está en 'Egreso Completo'. (Tarea: {task.name})")

            # Buscar productos con el paquete de facturación de almacenamiento
            base_domain = [('stock_invoice_pack', '=', True)]
            imo_general_domain = ['|', ('product_tmpl_id.is_general', '=', True), '&', ('product_tmpl_id.is_general', '=', False), ('is_imo', '=', task.is_imo)]
            domain = base_domain + imo_general_domain

            products = self.env['product.product'].search(domain)
            if not products:
                raise ValidationError('No hay productos configurados para facturación de almacenamiento.')

            # Calcular el mes y año de la factura
            invoice_date = fields.Date.today()
            mes_factura = invoice_date.strftime('%B').capitalize()  # Nombre del mes en español
            anio_factura = invoice_date.strftime('%Y')

            # Calcular el periodo facturado
            inicio_periodo = invoice_date.replace(day=1).strftime('%d/%m/%Y')
            fin_periodo = (invoice_date.replace(day=1).replace(month=invoice_date.month % 12 + 1) - timedelta(days=1)).strftime('%d/%m/%Y')

            # Preparar el contenido del campo narration
            narration = (
                "NOTA DE MENSUAL<br/>"
                f"CORRESPONDE AL ALMACENAJE MENSUAL {mes_factura.upper()} {anio_factura}<br/>"
                f"Periodo Facturado: {inicio_periodo} al {fin_periodo}<br/><br/>"
                "Banco Santander<br/>"
                "CBU: 0720429020000000055554<br/>"
                "Banco Credicoop<br/>"
                "CBU: 1910246555024600234278<br/><br/>"
                "BAJA EN IIBB CABA - BS AS DESDE 31/08/2024"
            )

            # Crear la factura (account.move)
            invoice = account_move_obj.create({
                'partner_id': task.partner_id.id,
                'move_type': 'out_invoice',
                'invoice_origin': task.name,
                'invoice_date': invoice_date,
                'narration': narration,  # Agregar la narración
            })

            _logger.info(f"Factura creada con ID: {invoice.id} para la tarea {task.name} (ID: {task.id})")

            # Obtener la tasa de cambio de USD
            usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
            if not usd_currency:
                raise ValidationError("No se encontró la divisa USD en el sistema.")

            rate = 1 / usd_currency.rate # Tasa de cambio actual de USD
            _logger.info(f"Tasa de cambio USD: {rate}")

            if not task.fecha_ingreso:
                raise ValidationError(f"La tarea {task.name} no tiene definida la fecha de ingreso.")

            # Validar si la fecha de la factura está en el mismo mes que la fecha_ingreso
            factura_mes = invoice.invoice_date.month
            factura_anio = invoice.invoice_date.year
            ingreso_mes = task.fecha_ingreso.month
            ingreso_anio = task.fecha_ingreso.year

            # Obtener el total de días del mes actual
            # invoice_date is already a date object here
            # days_in_invoice_full_month calculation
            _, days_in_invoice_full_month = calendar.monthrange(invoice_date.year, invoice_date.month)
            
            _logger.info(f"Días totales del mes {invoice_date.strftime('%B')}: {days_in_invoice_full_month}")

            # Agregar líneas de factura
            for product in products:
                if product.product_tmpl_id.fob_total:
                    # No agregar la línea FOB si task.fecha_ingreso es el mismo mes y año que invoice_date
                    if task.fecha_ingreso and not (invoice.invoice_date.month == task.fecha_ingreso.month and invoice.invoice_date.year == task.fecha_ingreso.year):
                        quantity = 1
                        fob_total = task.total_fob
                        calculate_custom = True # This should be true for FOB lines if they have custom logic
                        name = f"{task.name} - Fob total:{task.total_fob} - USD:{rate}"
                        _logger.info(f"Agregando producto FOB - Tipo de cambio {rate} - Total FOB {task.total_fob} - Fecha Ingreso: {task.fecha_ingreso} - Fecha Factura: {invoice.invoice_date}")

                        account_move_line_obj.create({
                            'move_id': invoice.id,
                            'product_id': product.id,
                            'quantity': quantity,
                            'calculate_custom': calculate_custom,
                            'fob_total': fob_total,
                            'name': name,
                            'account_id': product.categ_id.property_account_income_categ_id.id,
                            'task_id': task.id,
                        })
                    else:
                        _logger.info(f"Producto FOB {product.name} omitido para la tarea {task.name} porque task.fecha_ingreso ({task.fecha_ingreso}) está en el mismo mes/año que invoice_date ({invoice.invoice_date})")

                elif product.product_tmpl_id.is_storage:
                    current_task_storage_days = 0
                    if task.fecha_ingreso:
                        # invoice.invoice_date is invoice_date in this scope
                        if invoice_date.year == task.fecha_ingreso.year and invoice_date.month == task.fecha_ingreso.month:
                            _, num_days_in_invoice_month_for_task = calendar.monthrange(invoice_date.year, invoice_date.month)
                            last_day_of_invoice_month_date = invoice_date.replace(day=num_days_in_invoice_month_for_task)
                            current_task_storage_days = (last_day_of_invoice_month_date - task.fecha_ingreso).days + 1
                        else: # Entry date is in a previous month/year
                            current_task_storage_days = days_in_invoice_full_month
                    else:
                        # Default to full month if fecha_ingreso is somehow not set (though validated earlier)
                        current_task_storage_days = days_in_invoice_full_month
                        _logger.warning(f"Tarea {task.name} no tiene fecha_ingreso definida al calcular días de almacenaje. Usando mes completo: {current_task_storage_days} días.")

                    quantity = task.total_m3 or 1.0 # Ensure quantity is not zero
                    calculate_custom = True # For storage products, custom calculation is expected in account.move.line
                    
                    # Determine daily rate: from pricelist or fallback to product's list_price
                    daily_rate_to_use = product.product_tmpl_id.list_price # Default fallback
                    if invoice.pricelist_id:
                        price_context_quantity = quantity if quantity > 0 else 1 # Pricelist rules might need qty > 0
                        price_context = {
                            'pricelist': invoice.pricelist_id.id,
                            'partner': invoice.partner_shipping_id.id or invoice.partner_id.id,
                            'quantity': price_context_quantity,
                            'date': invoice.invoice_date,
                            'uom': product.uom_id.id,
                        }
                        try:
                            pricelist_rate = product.with_context(price_context).price
                            if pricelist_rate is not False and pricelist_rate != daily_rate_to_use: # Check if a different price was found
                                daily_rate_to_use = pricelist_rate
                                _logger.info(f"Storage product {product.name} (Task: {task.name}): Fetched daily rate {daily_rate_to_use} using Pricelist: {invoice.pricelist_id.name}")
                            else:
                                _logger.info(f"Storage product {product.name} (Task: {task.name}): Pricelist {invoice.pricelist_id.name} did not return a specific rate, using fallback/default list price {daily_rate_to_use}.")
                        except Exception as e:
                            _logger.error(f"Error fetching price from pricelist for product {product.name} (Task: {task.name}): {e}. Using fallback list price {daily_rate_to_use}.")
                    else:
                        _logger.info(f"Storage product {product.name} (Task: {task.name}): No pricelist on invoice. Using product list price {daily_rate_to_use} as daily rate.")

                    name = f"{product.name} - {task.name} - {quantity} m3 - {current_task_storage_days} días"

                    account_move_line_obj.create({
                        'move_id': invoice.id,
                        'product_id': product.id,
                        'quantity': quantity, # Actual m3 for the line
                        'days_storage': current_task_storage_days,
                        'calculate_custom': calculate_custom,
                        'price_unit': daily_rate_to_use, # Use the pricelist-derived or fallback rate
                        'name': name,
                        'account_id': product.categ_id.property_account_income_categ_id.id,
                        'task_id': task.id,
                    })
                else:
                    # Para productos sin fob_total ni is_storage, usar el total_m3 como cantidad
                    quantity = 1
                    name = f"{product.name} - {task.name}"
                    calculate_custom = False

                    account_move_line_obj.create({
                        'move_id': invoice.id,
                        'product_id': product.id,
                        'quantity': quantity,
                        'calculate_custom': calculate_custom,
                        'price_unit': product.lst_price,
                        'name': name,
                        'account_id': product.categ_id.property_account_income_categ_id.id,
                        'task_id': task.id,
                    })

            try:
                invoice.button_update_prices_from_pricelist()
            except Exception as e:
                _logger.error(f"Error al actualizar precios para la factura {invoice.id}: {str(e)}")
            
            
            # Abrir la factura recién creada
            return {
                'type': 'ir.actions.act_window',
                'name': 'Factura',
                'res_model': 'account.move',
                'view_mode': 'form',
                'res_id': invoice.id,
                'target': 'current',
            }

    def _cron_generate_storage_invoices(self):
        account_move_obj = self.env['account.move']
        account_move_line_obj = self.env['account.move.line']
        tasks = self.search([])  # Ajusta el dominio según sea necesario

        for task in tasks:
            if task.egreso_completo:
                # Ignorar tareas con egreso_completo=True
                continue

            if not task.project_id.importation:
                # Ignorar tareas cuyo proyecto no tiene importation=True
                continue

            if task.date_next_billing and task.date_next_billing > fields.Date.today():
                # Ignorar tareas cuya próxima fecha de facturación es mayor a la fecha actual
                continue

            # Buscar productos asociados al campo específico
            products = self.env['product.product'].search([('product_tmpl_id.outcome_invoice_pack', '=', True)])
            if not products:
                raise ValidationError('No hay productos configurados con el paquete solicitado.')

            # Crear la factura
            invoice = account_move_obj.create({
                'partner_id': task.partner_id.id,
                'move_type': 'out_invoice',  # Factura de cliente
                'invoice_origin': f"Storage - {task.name}",
            })
            _logger.info(f"Factura creada con ID: {invoice.id} para la tarea {task.name} (ID: {task.id})")

            # Agregar líneas de factura
            for product in products:
                line = account_move_line_obj.create({
                    'move_id': invoice.id,
                    'product_id': product.id,
                    'quantity': 1,  # Ajusta según sea necesario
                    'price_unit': product.lst_price,
                    'name': f"{product.name} - {task.name}",
                    'account_id': product.categ_id.property_account_income_categ_id.id,
                    'task_id': task.id,  # Relación con la tarea
                })
                _logger.info(f"Línea de factura creada con ID: {line.id}, relacionada con la tarea {task.name} (ID: {task.id})")
            
            try:
                invoice.button_update_prices_from_pricelist()
            except Exception as e:
                _logger.error(f"Error al actualizar precios para la factura {invoice.id}: {str(e)}")

            # Verificar si las líneas tienen el task_id asignado
            for line in invoice.invoice_line_ids:
                _logger.info(f"Línea de factura {line.id} asociada a la tarea {line.task_id.id if line.task_id else 'No asignada'}")

        return True

    def _create_single_task_invoice(self, task):
        account_move_obj = self.env['account.move']
        account_move_line_obj = self.env['account.move.line']

        # Validación de egreso_completo
        if task.egreso_completo:
            raise ValidationError(f"Este tránsito no se puede facturar porque está en 'Egreso Completo'. (Tarea: {task.name})")

        # Buscar productos con el paquete de facturación de almacenamiento
        base_domain = [('stock_invoice_pack', '=', True)]
        imo_general_domain = ['|', ('product_tmpl_id.is_general', '=', True), '&', ('product_tmpl_id.is_general', '=', False), ('is_imo', '=', task.is_imo)]
        domain = base_domain + imo_general_domain
        products = self.env['product.product'].search(domain)
        if not products:
            raise ValidationError(f"No hay productos configurados para facturación de almacenamiento para la tarea {task.name}.")

        # Calcular fecha y período para la narración
        invoice_date = fields.Date.today()
        mes_factura = invoice_date.strftime('%B').capitalize()
        anio_factura = invoice_date.strftime('%Y')
        
        # Calcular el periodo facturado
        inicio_periodo = invoice_date.replace(day=1).strftime('%d/%m/%Y')
        fin_periodo = (invoice_date.replace(day=1).replace(month=invoice_date.month % 12 + 1) - timedelta(days=1)).strftime('%d/%m/%Y')

        # Preparar narración
        narration = (
            "NOTA DE MENSUAL<br/>"
            f"CORRESPONDE AL ALMACENAJE MENSUAL {mes_factura.upper()} {anio_factura}<br/>"
            f"Periodo Facturado: {inicio_periodo} al {fin_periodo}<br/><br/>"
            "Banco Santander<br/>"
            "CBU: 0720429020000000055554<br/>"
            "Banco Credicoop<br/>"
            "CBU: 1910246555024600234278<br/><br/>"
            "BAJA EN IIBB CABA - BS AS DESDE 31/08/2024"
        )

        # Crear la factura para la tarea
        invoice = account_move_obj.create({
            'partner_id': task.partner_id.id,
            'move_type': 'out_invoice',
            'invoice_origin': task.name,
            'invoice_date': invoice_date,
            'narration': narration,
        })

        _logger.info(f"Factura creada con ID: {invoice.id} para la tarea {task.name} (ID: {task.id})")

        # Obtener tasa de cambio USD
        usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
        rate = 1.0
        if usd_currency:
            rate_data = usd_currency._get_rates(self.env.company, fields.Date.context_today(self))
            rate = 1 / rate_data.get(usd_currency.id, 1.0)

        # Agregar líneas de factura
        for product in products:
            # Determinar si el producto requiere cálculo personalizado
            calculate_custom = product.product_tmpl_id.is_storage or product.product_tmpl_id.fob_total

            if product.product_tmpl_id.fob_total:
                # No agregar la línea FOB si task.fecha_ingreso es el mismo mes y año que invoice_date
                if task.fecha_ingreso and not (invoice.invoice_date.month == task.fecha_ingreso.month and invoice.invoice_date.year == task.fecha_ingreso.year):
                    quantity = 1
                    name = f"{product.name} - {task.name} - Fob total:{task.total_fob} - USD:{rate}"
                    fob_total = task.total_fob

                    account_move_line_obj.create({
                        'move_id': invoice.id,
                        'product_id': product.id,
                        'quantity': quantity,
                        'calculate_custom': calculate_custom, # Ensure calculate_custom is defined correctly for this block
                        'fob_total': fob_total,
                        'name': name,
                        'account_id': product.categ_id.property_account_income_categ_id.id,
                        'task_id': task.id,
                    })
                else:
                    _logger.info(f"Producto FOB {product.name} omitido para la tarea {task.name} en factura individual porque task.fecha_ingreso ({task.fecha_ingreso}) está en el mismo mes/año que invoice_date ({invoice.invoice_date})")

            elif product.product_tmpl_id.is_storage:
                current_task_storage_days = 0
                # invoice.invoice_date is invoice_date in this method's scope
                _, days_in_invoice_full_month = calendar.monthrange(invoice_date.year, invoice_date.month)

                if task.fecha_ingreso:
                    if invoice_date.year == task.fecha_ingreso.year and invoice_date.month == task.fecha_ingreso.month:
                        _, num_days_in_invoice_month_for_task = calendar.monthrange(invoice_date.year, invoice_date.month)
                        last_day_of_invoice_month_date = invoice_date.replace(day=num_days_in_invoice_month_for_task)
                        current_task_storage_days = (last_day_of_invoice_month_date - task.fecha_ingreso).days + 1
                    else: # Entry date is in a previous month/year
                        current_task_storage_days = days_in_invoice_full_month
                else:
                    current_task_storage_days = days_in_invoice_full_month
                    _logger.warning(f"Tarea {task.name} no tiene fecha_ingreso definida al calcular días de almacenaje para factura individual. Usando mes completo: {current_task_storage_days} días.")

                quantity = task.total_m3 or 1.0
                # calculate_custom is already defined based on product.product_tmpl_id.is_storage or fob_total

                # Determine daily rate: from pricelist or fallback to product's list_price
                daily_rate_to_use = product.product_tmpl_id.list_price # Default fallback
                if invoice.pricelist_id:
                    price_context_quantity = quantity if quantity > 0 else 1 # Pricelist rules might need qty > 0
                    price_context = {
                        'pricelist': invoice.pricelist_id.id,
                        'partner': invoice.partner_shipping_id.id or invoice.partner_id.id,
                        'quantity': price_context_quantity,
                        'date': invoice.invoice_date,
                        'uom': product.uom_id.id,
                    }
                    try:
                        pricelist_rate = product.with_context(price_context).price
                        if pricelist_rate is not False and pricelist_rate != daily_rate_to_use: # Check if a different price was found
                            daily_rate_to_use = pricelist_rate
                            _logger.info(f"Storage product {product.name} (Task: {task.name}, Single Invoice): Fetched daily rate {daily_rate_to_use} using Pricelist: {invoice.pricelist_id.name}")
                        else:
                            _logger.info(f"Storage product {product.name} (Task: {task.name}, Single Invoice): Pricelist {invoice.pricelist_id.name} did not return a specific rate, using fallback/default list price {daily_rate_to_use}.")
                    except Exception as e:
                        _logger.error(f"Error fetching price from pricelist for product {product.name} (Task: {task.name}, Single Invoice): {e}. Using fallback list price {daily_rate_to_use}.")
                else:
                    _logger.info(f"Storage product {product.name} (Task: {task.name}, Single Invoice): No pricelist on invoice. Using product list price {daily_rate_to_use} as daily rate.")

                name = f"{product.name} - {task.name} - {quantity} m3 - {current_task_storage_days} días"

                account_move_line_obj.create({
                    'move_id': invoice.id,
                    'product_id': product.id,
                    'quantity': quantity,
                    'days_storage': current_task_storage_days, # Changed from task.days_to_invoiced
                    'calculate_custom': calculate_custom,
                    'price_unit': daily_rate_to_use, # Use the pricelist-derived or fallback rate
                    'name': name,
                    'account_id': product.categ_id.property_account_income_categ_id.id,
                    'task_id': task.id,
                })
            else:
                # Productos normales
                account_move_line_obj.create({
                    'move_id': invoice.id,
                    'product_id': product.id,
                    'quantity': 1,
                    'calculate_custom': False,
                    'price_unit': product.lst_price,
                    'name': f"{product.name} - {task.name}",
                    'account_id': product.categ_id.property_account_income_categ_id.id,
                    'task_id': task.id,
                })

        # Actualizar precios según lista de precios
        try:
            invoice.button_update_prices_from_pricelist()
        except Exception as e:
            _logger.error(f"Error al actualizar precios para la factura {invoice.id}: {str(e)}")

        return invoice

    # echo ok: sumarizar fob total en le producto seguros (revisar config producto) de todos los transitos que esten unificados en la factura. En el almacenamiento mensual desde tareas revisar que se haya implementado la linea del producto seguro (fob)
    def action_generate_monthly_invoices(self):
        # Agrupar tareas por cliente y por IMO
        grouped_tasks = {}
        invalid_tasks = []
        
        _logger.info("Iniciando el proceso de generación de facturas mensuales...")

        created_invoice_ids = [] # Initialize list to store created invoice IDs
        # Primera agrupación: por cliente y por IMO
        for task in self:
            if task.egreso_completo:
                invalid_tasks.append(task)
                continue

            partner = task.partner_id
            if partner.monthly_invoice:
                # Clave compuesta: (partner_id, is_imo)
                key = (partner.id, task.is_imo)
                if key not in grouped_tasks:
                    grouped_tasks[key] = []
                grouped_tasks[key].append(task)
            else:
                # Crear factura individual
                invoice_obj = self._create_single_task_invoice(task)
                if invoice_obj:
                    created_invoice_ids.append(invoice_obj.id)


        if invalid_tasks:
            task_names = ', '.join([task.name for task in invalid_tasks])
            raise ValidationError(f"Las siguientes tareas tienen 'Egreso Completo' en True y no se facturarán: {task_names}")

        # Procesar grupos de tareas
        for (partner_id, is_imo), tasks in grouped_tasks.items():
            partner = self.env['res.partner'].browse(partner_id)
            
            # Calcular fecha y período
            invoice_date = fields.Date.today()
            mes_factura = invoice_date.strftime('%B').capitalize()
            anio_factura = invoice_date.strftime('%Y')
            
            # Calcular días del mes
            # invoice_date is already a date object
            _, days_in_invoice_full_month = calendar.monthrange(invoice_date.year, invoice_date.month)

            # Preparar narración
            inicio_periodo = invoice_date.replace(day=1).strftime('%d/%m/%Y')
            fin_periodo = (ultimo_dia_mes - timedelta(days=1)).strftime('%d/%m/%Y')
            narration = (
                "NOTA DE MENSUAL<br/>"
                f"CORRESPONDE AL ALMACENAJE MENSUAL {mes_factura.upper()} {anio_factura}<br/>"
                f"Periodo Facturado: {inicio_periodo} al {fin_periodo}<br/><br/>"
                "Banco Santander<br/>"
                "CBU: 0720429020000000055554<br/>"
                "Banco Credicoop<br/>"
                "CBU: 1910246555024600234278<br/><br/>"
                "BAJA EN IIBB CABA - BS AS DESDE 31/08/2024"
            )

            # Crear factura
            invoice = self.env['account.move'].create({
                'partner_id': partner.id,
                'move_type': 'out_invoice',
                'invoice_origin': ', '.join([task.name for task in tasks]),
                'invoice_date': invoice_date,
                'narration': narration,
            })
            if invoice: # If grouped invoice was created
                created_invoice_ids.append(invoice.id)

            # Obtener productos según IMO
            base_domain = [('stock_invoice_pack', '=', True)]
            imo_general_domain = ['|', ('product_tmpl_id.is_general', '=', True), '&', ('product_tmpl_id.is_general', '=', False), ('is_imo', '=', is_imo)]
            domain = base_domain + imo_general_domain
            products = self.env['product.product'].search(domain)

            # Obtener tasa de cambio USD
            usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
            if not usd_currency:
                raise ValidationError("No se encontró la divisa USD en el sistema.")
            rate = 1 / usd_currency.rate

            # Procesar productos
            for product in products:
                if product.product_tmpl_id.fob_total:
                    total_fob_for_invoice = 0
                    task_details_for_invoice = []
                    # invoice_date is defined earlier in this method
                    for task_in_group in tasks: # 'tasks' is the list of tasks for the current group
                        if task_in_group.total_fob and task_in_group.fecha_ingreso:
                            if not (invoice.invoice_date.month == task_in_group.fecha_ingreso.month and invoice.invoice_date.year == task_in_group.fecha_ingreso.year):
                                total_fob_for_invoice += task_in_group.total_fob
                                task_details_for_invoice.append(f"{task_in_group.name}: {task_in_group.total_fob}")
                            else:
                                _logger.info(f"FOB para tarea {task_in_group.name} omitido en factura agrupada porque fecha_ingreso ({task_in_group.fecha_ingreso}) es mismo mes/año que fecha factura ({invoice.invoice_date})")

                    if total_fob_for_invoice > 0:
                        name = f"FOB Total - {' | '.join(task_details_for_invoice)} - USD:{rate}"
                        self.env['account.move.line'].create({
                            'move_id': invoice.id,
                            'product_id': product.id,
                            'quantity': 1,
                            'calculate_custom': True,
                            'fob_total': total_fob_for_invoice,
                            'name': name,
                            'account_id': product.categ_id.property_account_income_categ_id.id,
                            # No task_id here as it's a consolidated line for multiple tasks
                        })

                elif product.product_tmpl_id.is_storage:
                    # Crear línea por cada tarea para storage
                    for task_in_group in tasks: # Renamed 'task' to 'task_in_group' to avoid conflict with outer scope if any
                        current_task_storage_days = 0
                        if task_in_group.fecha_ingreso:
                            # invoice.invoice_date is invoice_date in this scope
                            if invoice_date.year == task_in_group.fecha_ingreso.year and invoice_date.month == task_in_group.fecha_ingreso.month:
                                _, num_days_in_invoice_month_for_task = calendar.monthrange(invoice_date.year, invoice_date.month)
                                last_day_of_invoice_month_date = invoice_date.replace(day=num_days_in_invoice_month_for_task)
                                current_task_storage_days = (last_day_of_invoice_month_date - task_in_group.fecha_ingreso).days + 1
                            else: # Entry date is in a previous month/year
                                current_task_storage_days = days_in_invoice_full_month
                        else:
                            current_task_storage_days = days_in_invoice_full_month
                            _logger.warning(f"Tarea {task_in_group.name} no tiene fecha_ingreso definida al calcular días de almacenaje para factura agrupada. Usando mes completo: {current_task_storage_days} días.")

                        quantity = task_in_group.total_m3 or 1.0

                        # Determine daily rate: from pricelist or fallback to product's list_price
                        daily_rate_to_use = product.product_tmpl_id.list_price # Default fallback
                        if invoice.pricelist_id:
                            price_context_quantity = quantity if quantity > 0 else 1 # Pricelist rules might need qty > 0
                            price_context = {
                                'pricelist': invoice.pricelist_id.id,
                                'partner': invoice.partner_shipping_id.id or invoice.partner_id.id, # partner from the invoice
                                'quantity': price_context_quantity,
                                'date': invoice.invoice_date,
                                'uom': product.uom_id.id,
                            }
                            try:
                                pricelist_rate = product.with_context(price_context).price
                                if pricelist_rate is not False and pricelist_rate != daily_rate_to_use: # Check if a different price was found
                                    daily_rate_to_use = pricelist_rate
                                    _logger.info(f"Storage product {product.name} (Task: {task_in_group.name}, Grouped Invoice): Fetched daily rate {daily_rate_to_use} using Pricelist: {invoice.pricelist_id.name}")
                                else:
                                    _logger.info(f"Storage product {product.name} (Task: {task_in_group.name}, Grouped Invoice): Pricelist {invoice.pricelist_id.name} did not return a specific rate, using fallback/default list price {daily_rate_to_use}.")
                            except Exception as e:
                                _logger.error(f"Error fetching price from pricelist for product {product.name} (Task: {task_in_group.name}, Grouped Invoice): {e}. Using fallback list price {daily_rate_to_use}.")
                        else:
                             _logger.info(f"Storage product {product.name} (Task: {task_in_group.name}, Grouped Invoice): No pricelist on invoice. Using product list price {daily_rate_to_use} as daily rate.")

                        name = f"{product.name} - {task_in_group.name} - {quantity} m3 - {current_task_storage_days} días"

                        self.env['account.move.line'].create({
                            'move_id': invoice.id,
                            'product_id': product.id,
                            'quantity': quantity,
                            'days_storage': current_task_storage_days,
                            'calculate_custom': True,
                            'price_unit': daily_rate_to_use, # Use the pricelist-derived or fallback rate
                            'name': name,
                            'account_id': product.categ_id.property_account_income_categ_id.id,
                            'task_id': task_in_group.id,
                        })
                else:
                    # Productos normales
                    for task in tasks:
                        name = f"{product.name} - {task.name}"
                        self.env['account.move.line'].create({
                            'move_id': invoice.id,
                            'product_id': product.id,
                            'quantity': 1,
                            'calculate_custom': False,
                            'price_unit': product.lst_price,
                            'name': name,
                            'account_id': product.categ_id.property_account_income_categ_id.id,
                            'task_id': task.id,
                        })

            try:
                invoice.button_update_prices_from_pricelist()
            except Exception as e:
                _logger.error(f"Error al actualizar precios para la factura {invoice.id}: {str(e)}")

        _logger.info("Proceso de generación de facturas mensuales completado")

        if not created_invoice_ids:
            _logger.info("No invoices were generated by action_generate_monthly_invoices.")
            # Consider raising UserError if no invoices are generated and it's unexpected
            # from odoo.exceptions import UserError
            # raise UserError(_("No invoices were generated for the selected tasks/partners."))
            return True

        action_vals = {
            'name': 'Generated Monthly Invoices (Testing)',
            'domain': [('id', 'in', created_invoice_ids)],
            'res_model': 'account.move',
            'type': 'ir.actions.act_window',
            'view_mode': 'tree,form',
            'views': [(False, 'tree'), (False, 'form')],
            'target': 'current',
        }

        # Optional: If only one invoice, open in form view directly
        # if len(created_invoice_ids) == 1:
        #     action_vals.update({
        #         'view_mode': 'form',
        #         'res_id': created_invoice_ids[0],
        #         'views': [(False, 'form')],
        #     })
        #     del action_vals['domain']


        _logger.info(f"Action to display generated invoices: {action_vals}")
        return action_vals


