# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    income_invoice_pack = fields.Boolean(string='Factura de ingreso')
    outcome_invoice_pack = fields.Boolean(string='Factura de Egreso')
    stock_invoice_pack = fields.Boolean(string='Factura de Almacenamiento')

    fob_total = fields.Boolean(string='Utilizar para linea FOB total')

    is_storage = fields.Boolean(string='Utilizar para linea Almacenamiento total')

    product_full_transit = fields.Boolean(string='Usar en tránsito completo')

    one_line_invoice = fields.Boolean(string='Unificar en una sola línea al facturar un egreso')

    min_price = fields.Float(string='Importe minimo de facturación', default=0.0)

    is_imo = fields.Boolean(string='Utilizar para facturación IMO')