from odoo import models, fields
from odoo.exceptions import ValidationError


class FtpDirectory(models.Model):
    _name = "ftp.list"
    _rec_name = "name"
    _description = "FTP/SFTP Directories"

    name = fields.Char(
        string="Directory Name",
        readonly=True
    )
    ftp_attachment_ids = fields.One2many(
        comodel_name="ftp.attachment",
        inverse_name="ftp_list_id",
        string="FTP List"
    )
    ftp_syncing_id = fields.Many2one(
        comodel_name="ftp.syncing",
        string="Linked FTP Instance",
        readonly=True,
        ondelete="cascade"
    )
    download_this = fields.Boolean(
        string="Download",
        help="If selected then this folder will be Downloaded"
    )
    upload_this = fields.Boolean(
        string="Upload",
        help="If selected then this folder will be Uploaded"
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Partner"
    )
    edi_config_table_id = fields.Many2one(
        comodel_name="edi.config.table",
        string="Mapping Model/Table"
    )
    mapping_table_search_using_xml_header = fields.Boolean(
        string="Searching the mapping table using the XML header?",
        copy=False,
        default=False,
        help="If you want to search your mapping table using the XML header of your XML file, please enable this option."
    )
    server_type = fields.Selection(
        selection=[('sftp', 'SFTP'), ('ftp', 'FTP')],
        string="Server Type"
    )
    sftp_syncing_id = fields.Many2one(
        comodel_name="sftp.syncing",
        string="Linked SFTP Instance",
        readonly=True,
        ondelete="cascade"
    )
    daily_new_file = fields.Boolean(
        string='Daily new file coming in this directory?',
        copy=False,
        default=False,
        help='If a new file with the same name arrives daily in your directory and needs processing, please enable this option.'
    )
    split_records = fields.Boolean(
        string='Split the records of a file',
        copy=False,
        default=False,
        help='If a file is too large in size or contains too many records, split its records to ensure smooth processing.'
    )
    main_record_xml_element = fields.Char(
        string="XML Split Tag",
        copy=False,
        help='Specify the XML tag from which you want to split the file. '
             'For example, write "product" to split at <product>.'
    )
    cron_created = fields.Boolean(
        string="Cron Created",
        default=False,
        copy=False
    )

    def create_cron(self):
        """
        This method is used to create cron directory wise from button.
        Author: DG
        """
        code_method = 'model.sync_inner_files_directory_wise({0})'.format(self.id)
        existing_cron = self.env['ir.cron'].search([('code', '=', code_method), ('active', 'in', [True, False])],
                                                   limit=1)
        if self.ftp_syncing_id:
            name = self.ftp_syncing_id.name
        else:
            name = self.sftp_syncing_id.name
        if existing_cron:
            existing_cron.name = "EDI [{0}] Directory: [{1}] Sync Inner Files Directory Wise".format(
                name, self.name)
            return True
        cron_name = "EDI [{0}] Directory: [{1}] Sync Inner Files Directory Wise".format(
                name, self.name)
        model_name = 'ftp.list'
        if self.ftp_syncing_id:
            self.ftp_syncing_id.create_cron_for_automation_task(cron_name, model_name, code_method,
                                                 interval_type='minutes', interval_number=40,
                                                 nextcall_timegap_minutes=20)
        else:
            self.sftp_syncing_id.create_cron_for_automation_task(cron_name, model_name, code_method,
                                                                interval_type='minutes', interval_number=40,
                                                                nextcall_timegap_minutes=20)
        self.cron_created = True
        return True

    def sync_inner_files_directory_wise(self, directory_id):
        """
        This method is used to sync inner files Directory wise from FTP folders.
        Author: DG
        """
        if directory_id:
            self = self.browse(directory_id)
        self.ensure_one()
        if self.download_this:
            if self.ftp_syncing_id:
                self.ftp_syncing_id.sync_inner_files(ftp_list_obj=self)
            else:
                self.sftp_syncing_id.sync_sftp_inner_files(sftp_list_obj=self)
        else:
            raise ValidationError("You need to enable download configuration for this directory.")
