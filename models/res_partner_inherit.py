# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ResPartnerInherit(models.Model):
    _inherit = "res.partner"

    monthly_invoice = fields.Boolean('Unica factura mensual', default=False)