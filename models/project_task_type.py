# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class ProjectTaskType(models.Model):
    _inherit = 'project.task.type'

    transito_cerrado = fields.Boolean(string='Tránsito cerrado')
