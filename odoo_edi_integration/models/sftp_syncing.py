import logging
import stat
import os
import tempfile
import paramiko
import xmltodict
from odoo import api, fields, models, _
import base64
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, timedelta


_logger = logging.getLogger(__name__)


class SFTPSyncing(models.Model):
    _name = 'sftp.syncing'
    _description = "SFTP Syncing"

    name = fields.Char(
        string='Name'
    )
    is_verified = fields.Boolean(
        string='Verified ?'
    )
    sftp_host = fields.Char(
        "Host"
    )
    sftp_username = fields.Char(
        "User Name"
    )
    sftp_password = fields.Char(
        "Password"
    )
    sftp_port = fields.Char(
        "Port"
    )
    file_import_path = fields.Char(
        "File Import Path"
    )
    cron_created = fields.Boolean(
        string="Cron Created"
    )
    ftp_directory_ids = fields.One2many(
        comodel_name="ftp.list",
        inverse_name="sftp_syncing_id",
        string="DIRECTORY LISTS",
        auto_join=True
    )

    # Authentication Option Fields
    sftp_auth_method = fields.Selection(
        selection=[('password', 'Password'), ('pem_key', 'PEM/PPK Key')],
        string='Authentication Method',
        default='password',
        help="Select method for authentication."
    )
    sftp_pem_key = fields.Binary(
        string="PEM Key File",
        help="Upload the PEM private key file for key-based authentication."
    )
    sftp_pem_passphrase = fields.Char(
        string="PEM Key Passphrase",
        help="The passphrase for your PEM key, if Passphrase is configured during key generation."
    )

    def check_sftp_connection(self):
        """
        This method is used to connect SFTP with using host, port, username & password.
        Author: JJ
        """
        try:
            sftp_host = self.sftp_host
            sftp_username = self.sftp_username
            sftp_port = int(self.sftp_port)

            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connect_parameters = {
                'hostname' : sftp_host,
                'username' : sftp_username,
                'port' : sftp_port or 2222
            }

            temp_key_file_path = None

            if self.sftp_auth_method == 'password':
                sftp_password = '' if self._context.get('sftp_password') else self.sftp_password
                connect_parameters['password'] = sftp_password
                _logger.info(f"----------Login to SFTP via Username and Password.----------")

            else:
                with tempfile.NamedTemporaryFile(delete=False, mode='wb') as temp_key_file:
                    temp_key_file.write(base64.b64decode(self.sftp_pem_key))
                    temp_key_file.close()
                temp_key_file_path = temp_key_file.name
                with open(temp_key_file_path, "r+") as f:
                    lines = f.readlines()
                    lines[0] = "-----BEGIN OPENSSH PRIVATE KEY-----\n"
                    lines[-1] = "-----END OPENSSH PRIVATE KEY-----"
                    f.seek(0)
                    f.writelines(lines)
                    f.truncate()
                    f.close()
                connect_parameters['key_filename'] = temp_key_file_path

                if self.sftp_pem_passphrase:
                    connect_parameters['passphrase'] = self.sftp_pem_passphrase
                _logger.info(f"----------Login to SFTP via PEM Key.----------")

            ssh.connect(**connect_parameters)
            sftp_client = ssh.open_sftp()
            return sftp_client

        except Exception as e:
            if not self._context.get('sftp_password'):
                raise UserError(_("SFTP Connection Test Failed! Here is what we got instead:\n %s") % (e))

        finally:
            if temp_key_file_path and os.path.exists(temp_key_file_path):
                os.unlink(temp_key_file_path)

    def action_check_sftp_disconnect(self):
        """
        This method is used to disconnect SFTP server.
        """
        self.with_context(sftp_password=True).check_sftp_connection()
        self.with_context({'is_check_connection_from_write': True}).write({'is_verified': False})

    def action_check_sftp_connection(self):
        """
        This method is used to check connection through form view's button & based on it set value in is_verified.
        Author: JJ
        """
        try:
            sftp_client = self.check_sftp_connection()
            if sftp_client:
                # title = _("SFTP Connection Test Succeeded!")
                # message = _("Everything seems properly set up!")
                self.with_context({'is_check_connection_from_write': True}).write({'is_verified': True})
                # return {
                #     'type': 'ir.actions.client',
                #     'tag': 'display_notification',
                #     'params': {
                #         'title': title,
                #         'message': message,
                #         'sticky': False,
                #     }
                # }
        except Exception as e:
            self.with_context({'is_check_connection_from_write': True}).write({'is_verified': False})
            raise UserError(_("Connection Failed! Here is what we got instead:\n %s") % (e))

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
            'sftp_syncing_id': self.id
        }])
        return True

    def setup_sync_inner_files_cron(self):
        """
        From this method fetch inner files cron creation process declared.
        """
        code_method = 'model.sync_sftp_inner_files({0})'.format(self.id)
        existing_cron = self.env['ir.cron'].search([('code', '=', code_method), ('active', 'in', [True, False])], limit=1)
        if existing_cron:
            existing_cron.name = "EDI: [{0}] Sync Inner Files from SFTP".format(self.name)
            return True
        cron_name = "EDI: [{0}] Sync Inner Files from SFTP".format(self.name)
        model_name = 'sftp.syncing'
        self.create_cron_for_automation_task(cron_name, model_name, code_method,
                                             interval_type='minutes', interval_number=40,
                                             nextcall_timegap_minutes=20)
        return True

    @api.model_create_multi
    def create(self, vals_list):
        """
        This method is used to check connection at the time of creating record of SFTP Syncing.
        Author: JJ
        """
        res = super(SFTPSyncing, self).create(vals_list)
        for rec in res:
            rec.action_check_sftp_connection()
            rec.setup_sync_inner_files_cron()
        return res

    def write(self, vals):
        """
        This method is used to check connection at the time of write record of SFTP Syncing.
        Author: JJ
        """
        res = super(SFTPSyncing, self).write(vals)
        if not self.env.context.get('is_check_connection_from_write'):
            for rec in self:
                rec.action_check_sftp_connection()
                rec.setup_sync_inner_files_cron()
        return res

    def fetch_sftp_directories(self, sftp, path):
        """
        Recursively fetch root directories and subdirectories from the given SFTP path,
        using the file_import_path for the initial directory.
        Author: JJ
        """
        directories = []

        try:
            print(f"Fetching directories under: {path}")
            entries = sftp.listdir_attr(path)  # Use listdir_attr for structured directory information
        except Exception as e:
            print(f"Error accessing {path}: {e}")
            return directories  # Return an empty list if the path is inaccessible

        for file_attr in entries:
            entry_path = f"{path}/{file_attr.filename}".replace('//', '/')

            if stat.S_ISDIR(file_attr.st_mode):  # Check if it's a directory
                print(f"Found directory: {entry_path}")
                directories.append(entry_path)
                # Recursively fetch subdirectories
                directories.extend(self.fetch_sftp_directories(sftp, entry_path))

        return directories

    def sftp_fetch_directory(self, sftp):
        """
        Sync SFTP directories with Odoo records.
        Author: JJ
        """
        # Fetch all directories from SFTP (starting from root)
        path = self.file_import_path
        listdir_attr = sorted(self.fetch_sftp_directories(sftp, path))
        print("Directories fetched from SFTP:", listdir_attr)

        # Fetch all existing directories in Odoo for this syncing record
        existing_directories = {
            rec.name for rec in self.env["ftp.list"].search([("sftp_syncing_id", "=", self.id)])
        }

        # Identify new directories to add
        new_directories = set(listdir_attr) - existing_directories
        for subdir in new_directories:
            self.env["ftp.list"].create({"name": subdir, "sftp_syncing_id": self.id, "server_type": 'sftp'})

        # Identify old directories to remove
        obsolete_directories = existing_directories - set(listdir_attr)
        if obsolete_directories:
            self.env["ftp.list"].search([("name", "in", list(obsolete_directories))]).unlink()

    def sftp_attachment_create(self, destination, sftp, sftp_folder):
        """
        This method is used to create SFTP attachment from SFTP files.
        Author: JJ
        """
        self.ensure_one()
        sftp_attach = self.env["ftp.attachment"]

        try:
            sftp.chdir(destination)
            print(f"Changed directory to: {destination}")
        except Exception as e:
            _logger.error(f"Failed to change directory to {destination}: {e}")
            return

        try:
            # Fetch all files from the SFTP folder
            files = sftp.listdir()
            valid_extensions = {'.xml'}
            files = [file for file in files if
                     file not in {'.', '..'} and any(file.endswith(ext) for ext in valid_extensions)]

            sftp_split = False
            if sftp_folder and sftp_folder.split_records:
                # If inside directory split file configuration enables, then below code will process & split files into multiple parts & then process it.
                sftp_split = True
                original_path = destination
                split_dir = destination.rstrip('/').split('/')[-1] + "_split"
                destination = destination + '/' + split_dir

                # Create split directory if not exists
                try:
                    sftp.chdir(split_dir)
                except IOError:
                    sftp.mkdir(split_dir)
                    sftp.chdir(split_dir)

                # Split tag fetch from directory configuration.
                split_tag = sftp_folder.main_record_xml_element
                if not split_tag:
                    raise ValueError("Split tag must be provided.")

                split_matched_files = []
                for file in files:
                    local_file = os.path.join(tempfile.gettempdir(), file)
                    with open(local_file, 'wb') as f:
                        sftp.get(f"{original_path}/{file}", local_file)
                    _logger.info(f"Downloaded file: {file}")

                    # From the original file create parts if records more than 2000.
                    split_files = sftp_folder.ftp_syncing_id.split_xml_file(local_file, split_tag, 2000)

                    for split_file in split_files:
                        # Uploads a local file which is divided into parts to the SFTP server inside split folder.
                        self.upload_sftp_file(sftp, split_file, f"{original_path}/{split_dir}")
                        split_matched_files.append(split_file.lstrip('/tmp/'))

                    # Remove the original file inside tmp folder.
                    os.remove(local_file)
                    _logger.info(f"Deleted original file: {local_file}")

                _logger.info("Old matched files => {}".format(files))
                files = split_matched_files  # Update matched_files
                _logger.info("New matched files => {}".format(split_matched_files))

            for name in files:

                file_name = os.path.join(destination, name)
                match_attach_rec = sftp_attach.search(
                    [("name", "=", file_name.strip()), ("ftp_list_id", "=", sftp_folder.id)], limit=1)
                if match_attach_rec:
                    # If some directory has a daily new file, then we rename the file name & process it.
                    if sftp_folder and sftp_folder.daily_new_file:
                        splited_name = name.split(".")
                        if len(splited_name) == 2:
                            f_name = f"{splited_name[0]}_{datetime.today().strftime('%Y-%m-%d_%H:%M:%S')}.{splited_name[1]}"
                        else:
                            f_name = name
                        file_name = os.path.join(destination, f_name)
                        match_attach_rec = None

                local_file = os.path.join(tempfile.gettempdir(), name)
                try:
                    if not sftp_split:
                        with open(local_file, "wb") as fp:
                            sftp.get(f"{destination}/{name}", local_file)
                except Exception as e:
                    _logger.error(f"Failed to retrieve file {name}: {e}")
                    continue

                with open(local_file, 'rb') as fp:
                    file_data = fp.read()
                    attachment_value = {
                        "name": file_name,
                        "res_model": "sftp.syncing",
                        "public": True,
                        "ftp_list_id": sftp_folder.id,
                        "sync_date": fields.Datetime.now(),
                        "file_content": file_data.decode("utf-8") if ("xml" in file_name) or (
                                "tmp" in file_name) else base64.b64encode(file_data),
                        "datas": base64.b64encode(file_data),
                    }

                if not match_attach_rec:
                    try:
                        sftp_attach.create(attachment_value)
                    except Exception as error:
                        _logger.info("Something went wrong at the time of creating attachment => {}".format(error))
                        attachment_value.update({"file_content": ""})
                        sftp_attach.create(attachment_value)
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
        except Exception as e:
            _logger.error(f"Error while processing files in {destination}: {e}")

    def sync_sftp_directory(self):
        """
        This method is used to sync directories from SFTP.
        Author: JJ
        """
        self.ensure_one()
        try:
            sftp = self.check_sftp_connection()
            self.sftp_fetch_directory(sftp)
        except Exception as e:
            raise ValidationError("Something went wrong \n {}".format(e))

    def sync_sftp_inner_files(self, sftp_sync_id=False, sftp_list_obj=False):
        """
        This method is used to sync inner files from SFTP folders.
        Author: JJ
        """
        if sftp_sync_id:
            self = self.browse(sftp_sync_id)
        self.ensure_one()
        sftp = self.check_sftp_connection()
        if not sftp_list_obj:
            sftp_list_obj = self.ftp_directory_ids.filtered(lambda x: x.download_this)
        is_edi_config_table = sftp_list_obj.filtered(
            lambda x: not x.mapping_table_search_using_xml_header and not x.edi_config_table_id)
        if is_edi_config_table:
            raise ValidationError("Mapping table not set on these directories %s" % (is_edi_config_table.mapped('name')))

        # Find out directories in which a download option configured, based on those directories fetch inner files of it.
        for sftp_folder in sftp_list_obj:
            try:
                self.sftp_attachment_create(sftp_folder.name, sftp, sftp_folder)
            except Exception as e:
                raise ValidationError("Something went wrong \n {}".format(e))

    def upload_sftp_file(self, sftp, local_path, sftp_directory):
        """
        This method is used to uploads a local file to the SFTP server.
        Author: DG
        """
        filename = os.path.basename(local_path)
        with open(local_path, "rb") as file:
            sftp.putfo(file, filename)
        _logger.info(f"Uploaded: {local_path} ➝ {sftp_directory}/{filename}")
