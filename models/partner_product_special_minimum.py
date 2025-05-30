# -*- coding: utf-8 -*-
from odoo import models, fields, api

class PartnerProductSpecialMinimum(models.Model):
    _name = 'partner.product.special.minimum'
    _description = 'Partner-Specific Minimum Product Price'

    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        required=True,
        ondelete='cascade'
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        help="Select the specific product variant for this special minimum."
    )
    special_min_price = fields.Float(
        string='Special Minimum Price',
        digits='Product Price', # Standard Odoo precision name for monetary values
        required=True,
        help="The special minimum invoice line subtotal for this partner and product."
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        index=True, # Good to index company_id for multi-company environments
        help="Company to which this rule applies."
    )

    _sql_constraints = [
        ('unique_partner_product_company', 'UNIQUE(partner_id, product_id, company_id)',
         'A special minimum price rule already exists for this partner, product, and company.')
    ]
