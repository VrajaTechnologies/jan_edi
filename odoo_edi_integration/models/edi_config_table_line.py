from odoo import models, fields, api
from odoo.exceptions import ValidationError


class EDIConfigTableLine(models.Model):
    _name = 'edi.config.table.line'
    _description = "EDI Config Table Line"
    _order = 'sequence'

    @api.onchange('odoo_field')
    def _set_main_model_name(self):
        """
        This method is used to store main model name into new field which can be used in config table line.
        Author: DG
        """
        for rec in self:
            model_name = rec.edi_config_table_id.model_id.model
            rec.field_to_store_main_model_name = model_name

    @api.onchange('odoo_field', 'xml_element')
    def _set_relational_model_name(self):
        """
        This method is used to store m2o model name into new field which can be used in config table line.
        Author: DG
        """
        for rec in self:
            model_name = rec.odoo_field.relation
            if rec.odoo_field.ttype == 'many2one':
                rec.field_to_store_m2o_model_name = model_name
            if rec.xml_element and ' ' in rec.xml_element:
                 rec.xml_element = "".join(rec.xml_element.split())

    edi_config_table_id = fields.Many2one(
        comodel_name='edi.config.table',
        ondelete="cascade"
    )
    xml_element = fields.Char(
        string="XML Element"
    )
    odoo_field = fields.Many2one(
        comodel_name='ir.model.fields',
        string="Selected Model Fields"
    )
    visible_search_field_for_m2o = fields.Boolean(
        default=False
    )
    field_of_m2o_field = fields.Many2one(
        comodel_name='ir.model.fields',
        string="Field to search for M2O")
    visible_selection_field_for_o2m = fields.Boolean(
        default=False
    )
    field_to_store_main_model_name = fields.Char(
        string='Main Model name',
        compute='_set_main_model_name'
    )
    field_to_store_m2o_model_name = fields.Char(
        string='M2O Model name'
    )
    sub_edi_config_table_id = fields.Many2one(
        comodel_name='edi.config.table',
        string='Sub Table'
    )
    sequence = fields.Integer(
        help='Used to order Companies in the company switcher',
        default=10
    )
    char_length = fields.Integer(
        string="Character length max",
        default=50,
        help="This option allows us to limit the number of characters for a field",
    )
    required = fields.Boolean(
        string="Required",
        help="If it's enable, The Element is required and will cause an error if value is not there.",
    )

    @api.onchange('odoo_field')
    def _onchange_mapping_model_from(self):
        """
        This method is used to display fields based on selected model &
        handle active/inactive m2o search field and sub-table field for o2m.
        Author: DG
        """
        res = {'domain': {'odoo_field': [], 'field_of_m2o_field': []}}
        if self.edi_config_table_id.model_id:
            res['domain']['odoo_field'] = [('model_id', '=', self.edi_config_table_id.model_id.name)]
            model_name = self.odoo_field.relation
            if self.odoo_field.ttype == 'many2one':
                self.visible_selection_field_for_o2m = False
                self.visible_search_field_for_m2o = True
                self.field_to_store_m2o_model_name = model_name
                res['domain']['field_of_m2o_field'] = [('model_id', '=', model_name)]
            elif self.odoo_field.ttype == 'one2many':
                self.visible_search_field_for_m2o = False
                self.field_of_m2o_field = False
                self.field_to_store_m2o_model_name = ''
                self.visible_selection_field_for_o2m = True
            else:
                self.visible_search_field_for_m2o = False
                self.visible_selection_field_for_o2m = False
                self.field_of_m2o_field = False
        else:
            raise ValidationError("Please select the Odoo model first.")
        return res
