from odoo import fields, models, api
from odoo.exceptions import ValidationError


class EdiExportRecordsWizard(models.TransientModel):
    _name = "edi.export.records.wizard"
    _description = "EDI Export Records Wizard"

    edi_config_table_id = fields.Many2one(
        comodel_name="edi.config.table",
        string="Mapping Table/Model",
    )
    product_ids = fields.Many2many(
        comodel_name='product.product',
        string="Products",
        help="You can select single or multiple products here."
    )

    @api.onchange('edi_config_table_id')
    def onchange_edi_config_table(self):
        """
        From this method checked selected mapping table is belongs to product.product only.
        Author: DG
        """
        if self.edi_config_table_id.model_id.model and self.edi_config_table_id.model_id.model != 'product.product':
            raise ValidationError("Mapping table must belongs to Product Variant(product.product).")

    def action_submit_button(self):
        """
        Author: DG
        Usage: From this method multiple products records will export.
        """
        records_need_to_export = self.product_ids.filtered(lambda x: not x.x_is_processed)
        if not records_need_to_export:
            raise ValidationError("Selected products already exported.")
        self.edi_config_table_id.export_process_for_multiple_records(records_need_to_export)
