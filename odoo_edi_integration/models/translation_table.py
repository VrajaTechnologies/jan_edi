from odoo import models, fields


class TranslationTable(models.Model):
    _name = 'translation.table'
    _description = 'Translation Table'
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _rec_name = 'xml_element'

    edi_config_table_id = fields.Many2one(
        comodel_name='edi.config.table',
        string='Mapping Table',
        tracking=True
    )
    xml_element = fields.Char(
        string='XML Element',
        copy=False,
        tracking=True,
        help='(e.g., AddressID, Email)'
    )
    xml_value = fields.Char(
        string='XML Value',
        tracking=True,
        help='(e.g., 36261, test@example.com)'
    )
    corresponding_odoo_value = fields.Char(
        string='Corresponding Odoo Value',
        tracking=True
    )
