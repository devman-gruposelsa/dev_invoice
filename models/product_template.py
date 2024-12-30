# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'


    income_invoice_pack = fields.Boolean(string='Factura de ingreso')
    out_invoice_pack = fields.Boolean(string='Factura de Egreso')
    stock_invoice_pack = fields.Boolean(string='Factura de Almacenamiento')
