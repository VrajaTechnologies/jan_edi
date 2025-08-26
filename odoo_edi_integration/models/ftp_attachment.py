from odoo import fields, models, api
import xmltodict
import logging

_logger = logging.getLogger(__name__)


class FtpAttachment(models.Model):
    _name = "ftp.attachment"
    _inherits = {"ir.attachment": "attachment_id"}
    _description = "Ftp Attachment"

    attachment_id = fields.Many2one(
        comodel_name="ir.attachment",
        string="Related Attachment",
        copy=False,
        readonly=True,
        required=True,
        ondelete="cascade"
    )
    ftp_list_id = fields.Many2one(
        comodel_name="ftp.list",
        string="Folder Directory",
        copy=False,
        ondelete="cascade"
    )
    sync_date = fields.Datetime(
        readonly=True,
        copy=False
    )
    file_content = fields.Text(
        string="Parsed content",
        readonly=True
    )

    def unlink(self):
        """
        This method is used to unlink Odoo attachment at the time of deleting ftp attachments.
        Author: DG
        """
        attachments_to_delete = self.mapped("attachment_id")
        res = super(FtpAttachment, self).unlink()
        attachments_to_delete.unlink()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        """
        This method is used to create records of EDI transactions when attachment record get created.
        Author: DG
        """
        attachments = super(FtpAttachment, self).create(vals_list)
        if self.env.context.get('from_controller'):
            _logger.info("Skipping edi.transaction creation because attachment is created from controller.")
            return attachments
        for rec in attachments:
            edi_transaction = self.env["edi.transactions"]
            edi_config_table_id = self.env['edi.config.table']
            if rec.ftp_list_id and rec.ftp_list_id.download_this and rec.ftp_list_id.mapping_table_search_using_xml_header:
                python_dict = xmltodict.parse(rec.file_content)
                xml_header = ''
                for key, value in python_dict.items():
                    xml_header = key
                if xml_header:
                    edi_config_table_id = self.env['edi.config.table'].search([('xml_header', '=', xml_header)], limit=1)
                if not edi_config_table_id:
                    _logger.info("Using XML header [{}] mapping table not found.".format(xml_header))
            elif rec.ftp_list_id.edi_config_table_id and rec.ftp_list_id.edi_config_table_id.edi_type == "Incoming":
                edi_config_table_id = rec.ftp_list_id.edi_config_table_id
            
            if edi_config_table_id and not edi_transaction.search([('name', '=', rec.name)]):
                edi_transaction.create(
                    {
                        "name": rec.name,
                        "edi_type": edi_config_table_id.edi_type,
                        "edi_config_table_id": edi_config_table_id.id,
                        "ftp_attachment_id": rec.id,
                        "xml_content": rec.file_content,
                        "edi_partner_id": rec.ftp_list_id.partner_id and rec.ftp_list_id.partner_id.id or False,
                    }
                )
        return attachments
