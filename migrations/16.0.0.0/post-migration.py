from odoo import api, SUPERUSER_ID

def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    moves = env['account.move'].search([])
    for move in moves:
        move._update_task_relations()