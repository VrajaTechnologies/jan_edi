import logging
import os
import ftplib
import xmltodict
import tempfile
from odoo import api, fields, models, _
from datetime import datetime, timedelta
import base64
from odoo.exceptions import UserError, ValidationError
from lxml import etree

_logger = logging.getLogger(__name__)


class FTPSyncing(models.Model):
    _name = 'ftp.syncing'
    _description = "FTP Syncing"

    name = fields.Char(
        string='Name'
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string="Supplier"
    )
    is_verified = fields.Boolean(
        string='Verified ?'
    )
    ftp_url = fields.Char(
        string='URL'
    )
    ftp_port = fields.Char(
        string='Port',
        default='21'
    )
    ftp_username = fields.Char(
        string='Username'
    )
    ftp_password = fields.Char(
        string='Password'
    )
    cron_created = fields.Boolean(
        string="Cron Created"
    )
    ftp_directory_ids = fields.One2many(
        comodel_name="ftp.list",
        inverse_name="ftp_syncing_id",
        string="DIRECTORY LISTS",
        auto_join=True
    )

    def check_ftp_connection(self):
        """
        This method is used to connect FTP with using url, port, username & password.
        Author: DG
        """
        try:
            ftp_password = '' if self._context.get('ftp_password') else self.ftp_password
            f = ftplib.FTP()
            f.connect(self.ftp_url, int(self.ftp_port), 800)
            f.login(self.ftp_username,ftp_password)
            return f
        except Exception as e:
            if not self._context.get('ftp_password'):
                raise UserError(_("FTP Connection Test Failed! Here is what we got instead:\n %s") % (e))

    def action_check_ftp_disconnect(self):
        """
        This method is used to disconnect FTP server.
        """
        self.with_context(ftp_password=True).check_ftp_connection()
        self.with_context({'is_check_connection_from_write': True}).write({'is_verified': False})

    def action_check_ftp_connection(self):
        """
        This method is used to check connection through form view's button & based on it set value in is_verified.
        Author: DG
        """
        try:
            self.check_ftp_connection()
            # title = _("Connection Test Succeeded!")
            # message = _("Everything seems properly set up!")
            self.with_context({'is_check_connection_from_write': True}).write({'is_verified': True})
        except Exception as e:
            self.with_context({'is_check_connection_from_write': True}).write({'is_verified': False})
            # title = _("Issue in Connection!")
            # message = _(e)
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': title,
        #         'message': message,
        #         'sticky': False
        #     }
        # }

    def create_cron_for_automation_task(self, cron_name, model_name, code_method, interval_number=10,
                                        interval_type='minutes', nextcall_timegap_minutes=10):
        """
        This method is used for create cron record.
        """
        self.env['ir.cron'].create([{
            'name': cron_name,
            'model_id': self.env['ir.model'].search([('model', '=', model_name)]).id,
            'state': 'code',
            'code': code_method,
            'interval_number': interval_number,
            'interval_type': interval_type,
            'nextcall': datetime.now() + timedelta(minutes=nextcall_timegap_minutes),
            'numbercall': -1,
            'doall': True,
            'ftp_syncing_id': self.id
        }])
        return True

    def setup_sync_inner_files_cron(self):
        """
        From this method fetch inner files cron creation process declared.
        """
        code_method = 'model.sync_inner_files({0})'.format(self.id)
        existing_cron = self.env['ir.cron'].search([('code', '=', code_method), ('active', 'in', [True, False])], limit=1)
        if existing_cron:
            existing_cron.name = "EDI: [{0}] Sync Inner Files from FTP".format(self.name)
            return True
        cron_name = "EDI: [{0}] Sync Inner Files from FTP".format(self.name)
        model_name = 'ftp.syncing'
        self.create_cron_for_automation_task(cron_name, model_name, code_method,
                                             interval_type='minutes', interval_number=40,
                                             nextcall_timegap_minutes=20)
        return True

    @api.model_create_multi
    def create(self, vals_list):
        """
        This method is used to check connection at the time of creating record of FTP Syncing.
        Author: DG
        """
        res = super(FTPSyncing, self).create(vals_list)
        for rec in res:
            rec.action_check_ftp_connection()
            rec.setup_sync_inner_files_cron()
        return res

    def write(self, vals):
        """
        This method is used to check connection at the time of write record of FTP Syncing.
        Author: DG
        """
        res = super(FTPSyncing, self).write(vals)
        if not self.env.context.get('is_check_connection_from_write'):
            for rec in self:
                rec.action_check_ftp_connection()
                rec.setup_sync_inner_files_cron()
        return res

    def fetch_directories(self, ftp, path='/'):
        """
        Recursively fetch root directories and subdirectories from the given FTP path.
        Author: DG
        """
        directories = []
        try:
            _logger.info(f"Fetching directories under: {path}")
            ftp.encoding = 'latin-1'
            is_nlst = False

            try:
                entries = list(ftp.mlsd(path))  # Ensure entries is a list
            except Exception as e:
                _logger.info(f"MLSD failed, falling back to NLST.\n{e}")
                is_nlst = True
                try:
                    entries = [(name, {}) for name in ftp.nlst(path)]  # Convert NLST result to MLSD-like format
                except Exception as e:
                    _logger.error(f"Failed to list directories using MLSD & NLST: {e}")
                    return []

            if not isinstance(entries, list):  # Ensure entries is iterable
                _logger.error(f"Unexpected response type from FTP: {type(entries)}")
                return []

            for entry in entries:
                if not isinstance(entry, tuple) or len(entry) != 2:
                    _logger.warning(f"Skipping unexpected entry format: {entry}")
                    continue  # Skip malformed entries

                name, facts = entry

                # Set entry_path based on whether MLSD or NLST was used
                if is_nlst:
                    entry_path = name  # NLST returns full path, no need to modify
                else:
                    entry_path = f"{path}/{name}".replace('//', '/')  # Ensure correct formatting for MLSD

                is_directory = facts.get('type') == 'dir' if facts else True  # Assume NLST entries are directories

                if is_directory:
                    try:
                        _logger.info(f"Trying to enter: {entry_path}")
                        ftp.cwd(entry_path)  # Confirm it's a directory
                        _logger.info(f"Found directory: {entry_path}")
                        directories.append(entry_path)

                        # Recursively fetch subdirectories
                        directories.extend(self.fetch_directories(ftp, entry_path))

                        ftp.cwd('..')  # Move back up after recursion
                    except Exception as e:
                        _logger.warning(f"Skipping {entry_path}: {e}")

        except Exception as e:
            _logger.error(f"Unexpected error while accessing {path}: {e}")

        return directories

    def ftp_fetch_directory(self, ftp):
        """
        This method is used to check connection at the time of write record of FTP Syncing.
        Author: DG
        """
        mlsd_directory = self.fetch_directories(ftp, '/')
        _logger.info(f"Final directory list: {mlsd_directory}")  # Debugging output

        for subdir in sorted(mlsd_directory):
            if not self.env["ftp.list"].search([("name", "=", subdir), ("ftp_syncing_id", "=", self.id)]):
                self.env["ftp.list"].create({"name": subdir, "ftp_syncing_id": self.id, "server_type": 'ftp'})

        # If any extra directory/old directory is still there in Odoo, then we find out & unlink it.
        difference_result = []
        for item in self.mapped("ftp_directory_ids.name"):
            if item not in sorted(mlsd_directory):
                difference_result.append(item)
        if difference_result:
            for directory in difference_result:
                self.env['ftp.list'].search([('name', '=', directory)]).unlink()

    def ftp_attachment_create(self, destination, ftp, ftp_folder):
        """
        This method is used to create FTP attachment from FTP files.
        Author: DG
        """
        self.ensure_one()
        ftp_attach = self.env["ftp.attachment"]
        ftp.cwd(destination)

        # Fetch all files from that FTP folder & prepared list.
        files = ftp.nlst()
        valid_extensions = {'.xml'}
        files = [file for file in files if
                 file not in {'.', '..'} and any(file.endswith(ext) for ext in valid_extensions)]

        ftp_split = False
        if ftp_folder and ftp_folder.split_records:
            # If inside directory split file configuration enables, then below code will process & split files into multiple parts & then process it.
            ftp_split = True
            original_path = destination
            split_dir = destination.rstrip('/').split('/')[-1] + "_split"
            destination = destination + '/' + split_dir

            # Create split directory if not exists
            try:
                ftp.cwd(split_dir)
            except Exception:
                ftp.mkd(split_dir)

            #Split tag fetch from directory configuration.
            split_tag = ftp_folder.main_record_xml_element
            if not split_tag:
                raise ValueError("Split tag must be provided.")

            split_matched_files = []
            for file in files:
                local_file = os.path.join(tempfile.gettempdir(), file)
                with open(local_file, 'wb') as f:
                    ftp.retrbinary(f"RETR {original_path}/{file}", f.write)
                _logger.info(f"Downloaded file: {file}")

                # From the original file create parts if records more than 2000.
                split_files = self.split_xml_file(local_file, split_tag, 2000)

                for split_file in split_files:
                    # Uploads a local file which is divided into parts to the FTP server inside split folder.
                    self.upload_ftp_file(ftp, split_file, f"{original_path}/{split_dir}")
                    split_matched_files.append(split_file.lstrip('/tmp/'))

                # Remove the original file inside tmp folder.
                os.remove(local_file)
                _logger.info(f"Deleted original file: {local_file}")

            _logger.info("Old matched files => {}".format(files))
            files = split_matched_files  # Update matched_files
            _logger.info("New matched files => {}".format(split_matched_files))

        for name in files:
            file_name = os.path.join(destination, name)
            match_attach_rec = ftp_attach.search(
                [("name", "=", file_name.strip()), ("ftp_list_id", "=", ftp_folder.id)], limit=1)
            if match_attach_rec:
                # If some directory has a daily new file, then we rename the file name & process it.
                if ftp_folder and ftp_folder.daily_new_file:
                    splited_name = name.split(".")
                    if len(splited_name) == 2:
                        f_name = f"{splited_name[0]}_{datetime.today().strftime('%Y-%m-%d_%H:%M:%S')}.{splited_name[1]}"
                    else:
                        f_name = name
                    file_name = os.path.join(destination, f_name)
                    match_attach_rec = None

            local_file = os.path.join(tempfile.gettempdir(), name)
            if not ftp_split:
                with open(local_file, 'wb') as f:
                    ftp.retrbinary(f"RETR {destination}/{name}", f.write)
            with open(local_file, 'rb') as fp:
                file_data = fp.read()
                attachment_value = {
                    "name": file_name,
                    "res_model": "ftp.syncing",
                    "public": True,
                    "ftp_list_id": ftp_folder.id,
                    "sync_date": fields.Datetime.now(),
                    "file_content": file_data.decode("utf-8", errors="ignore") if ("xml" in file_name) or (
                            "tmp" in file_name) else base64.b64encode(file_data),
                    "datas": base64.b64encode(file_data),
                }

            if not match_attach_rec:
                try:
                    ftp_attach.create(attachment_value)
                except Exception as error:
                    _logger.info("Something went wrong at the time of creating attachment => {}".format(error))
                    attachment_value.update({"file_content": ""})
                    ftp_attach.create(attachment_value)
                _logger.info(_("Created the attachment %s") % file_name)
            else:
                # If attachment already exists and if EDI transaction not created, so below process will create it.
                edi_transaction = self.env["edi.transactions"]
                edi_config_table_id = self.env['edi.config.table']
                if match_attach_rec.ftp_list_id and match_attach_rec.ftp_list_id.download_this and match_attach_rec.ftp_list_id.mapping_table_search_using_xml_header:
                    python_dict = xmltodict.parse(match_attach_rec.file_content)
                    xml_header = ''
                    for key, value in python_dict.items():
                        xml_header = key
                    if xml_header:
                        edi_config_table_id = self.env['edi.config.table'].search([('xml_header', '=', xml_header)],
                                                                                  limit=1)
                    if not edi_config_table_id:
                        _logger.info("Using XML header [{}] mapping table not found.".format(xml_header))
                elif match_attach_rec.ftp_list_id.edi_config_table_id and match_attach_rec.ftp_list_id.edi_config_table_id.edi_type == "Incoming":
                    edi_config_table_id = match_attach_rec.ftp_list_id.edi_config_table_id

                if edi_config_table_id and not edi_transaction.search([('name', '=', match_attach_rec.name)]):
                    edi_transaction.create(
                        {
                            "name": match_attach_rec.name,
                            "edi_type": edi_config_table_id.edi_type,
                            "edi_config_table_id": edi_config_table_id.id,
                            "ftp_attachment_id": match_attach_rec.id,
                            "xml_content": match_attach_rec.file_content,
                            "edi_partner_id": match_attach_rec.ftp_list_id.partner_id and match_attach_rec.ftp_list_id.partner_id.id or False,
                        }
                    )
            self._cr.commit()

    def sync_directory(self):
        """
        This method is used to sync directories from FTP.
        Author: DG
        """
        self.ensure_one()
        try:
            ftp = self.check_ftp_connection()
            self.ftp_fetch_directory(ftp)
        except Exception as e:
            raise ValidationError("Something went wrong \n {}".format(e))

    def sync_inner_files(self, ftp_sync_id=False, ftp_list_obj= False):
        """
        This method is used to sync inner files from FTP folders.
        Author: DG
        """
        if ftp_sync_id:
            self = self.browse(ftp_sync_id)
        self.ensure_one()
        ftp = self.check_ftp_connection()
        if not ftp_list_obj:
            ftp_list_obj = self.ftp_directory_ids.filtered(lambda x: x.download_this)
        is_edi_config_table = ftp_list_obj.filtered(
            lambda x: not x.mapping_table_search_using_xml_header and not x.edi_config_table_id)
        if is_edi_config_table:
            raise ValidationError("Mapping table not set on these directories %s" % (is_edi_config_table.mapped('name')))

        # Find out directories in which a download option configured, based on those directories fetch inner files of it.
        for ftp_folder in ftp_list_obj:
            try:
                self.ftp_attachment_create(ftp_folder.name, ftp, ftp_folder)
            except Exception as e:
                raise ValidationError("Something went wrong \n {}".format(e))

    def get_root_hierarchy(self, file_path, split_tag):
        """
        Parses the XML file to determine the hierarchy of the given split_tag (e.g., 'item').
        Returns the full path to the split_tag.
        Author: DG
        """
        hierarchy = []
        for event, elem in etree.iterparse(file_path, events=("start",)):
            hierarchy.append(elem.tag)
            if elem.tag == split_tag:
                return "/".join(hierarchy[:-1])  # Exclude the split_tag itself
        return None

    def split_xml_file(self, file_path, split_tag, records_per_file):
        """
        Splits an XML file dynamically while preserving the root structure.
        Handles cases where root structure may vary.
        Author: DG
        """
        # Determine the root hierarchy dynamically
        root_hierarchy = self.get_root_hierarchy(file_path, split_tag)
        if not root_hierarchy:
            raise ValueError(f"Could not determine the hierarchy for '{split_tag}' in {file_path}")

        root_tags = root_hierarchy.split("/")
        root_main_tag = root_tags[0]  # First element (e.g., "Products" or "Header")
        container_tags = root_tags[1:]  # Remaining structure (e.g., ["Products", "items"])

        context = etree.iterparse(file_path, events=("start", "end"))

        total_records = sum(1 for _, elem in etree.iterparse(file_path, events=("end",)) if elem.tag == split_tag)
        total_files = -(-total_records // records_per_file)  # Equivalent to ceil division
        _logger.info(f"Splitting {file_path} into {total_files} parts")

        split_files = []
        record_counter, file_index = 0, 1
        current_file = None

        for event, elem in context:
            if event == "end" and elem.tag == split_tag:
                if record_counter % records_per_file == 0:
                    if current_file:
                        # Close all container tags and root properly
                        for tag in reversed(container_tags):
                            current_file.write(f"</{tag}>\n".encode("utf-8"))
                        current_file.write(f"</{root_main_tag}>".encode("utf-8"))
                        current_file.close()

                    split_filename = f"{os.path.basename(file_path.rsplit('.', 1)[0])}_part{file_index}.xml"
                    split_filepath = os.path.join(tempfile.gettempdir(), split_filename)

                    # Open a new file and write the XML header and root structure dynamically
                    current_file = open(split_filepath, "wb")
                    current_file.write(f'<?xml version="1.0" encoding="UTF-8"?>\n'.encode("utf-8"))
                    for tag in root_tags:
                        current_file.write(f"<{tag}>\n".encode("utf-8"))

                    split_files.append(split_filepath)
                    file_index += 1

                # Write the <item> element to the current file
                current_file.write(etree.tostring(elem, pretty_print=True))
                record_counter += 1
                elem.clear()

        if current_file:
            # Close the last file properly
            for tag in reversed(container_tags):
                current_file.write(f"</{tag}>\n".encode("utf-8"))
            current_file.write(f"</{root_main_tag}>".encode("utf-8"))
            current_file.close()

        return split_files

    def upload_ftp_file(self, ftp, local_path, ftp_directory):
        """
        This method is used to uploads a local file to the FTP server.
        Author: DG
        """
        filename = os.path.basename(local_path)
        with open(local_path, "rb") as file:
            ftp.storbinary(f"STOR {ftp_directory}/{filename}", file)
        _logger.info(f"Uploaded: {local_path} ➝ {ftp_directory}/{filename}")
