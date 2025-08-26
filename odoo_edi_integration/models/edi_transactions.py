from odoo import fields, models, api
from odoo.exceptions import ValidationError
from odoo.tools.convert import safe_eval
from dateutil import parser
import xmltodict
import logging
import os

_logger = logging.getLogger(__name__)


class EDITransactions(models.Model):
    _name = "edi.transactions"
    _description = "EDI Transactions"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(
        tracking=True,
    )
    edi_config_table_id = fields.Many2one(
        comodel_name="edi.config.table",
        string="EDI Config Table",
        required=True,
        tracking=True,
        ondelete="cascade"
    )
    file_type = fields.Selection(
        related="edi_config_table_id.file_type"
    )
    log_id = fields.Many2one(
        comodel_name='log.book',
        copy=False
    )
    xml_content = fields.Text(
        string="Content",
        tracking=True,
    )
    state = fields.Selection(
        selection=[("Draft", "Draft"), ("Failed", "Failed"), ("Partially_Done", "Partially Done"),
                   ("Done", "Done"), ("Cancel", "Cancel")],
        default="Draft",
        tracking=True
    )
    edi_type = fields.Selection(
        selection=[('Incoming', 'Incoming'), ('Outgoing', 'Outgoing')],
        string="Type"
    )
    reference = fields.Reference(
        string="Related Document",
        selection="_reference_models",
        copy=False
    )
    reference_data = fields.Json(
        string="References"
    )
    ftp_attachment_id = fields.Many2one(
        comodel_name="ftp.attachment",
        ondelete="cascade"
    )
    edi_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="EDI Partner"
    )

    @api.model
    def _reference_models(self):
        """
        This method is used to provide reference model values from config table.
        Author: DG
        """
        edi_tables = self.env["edi.config.table"].sudo().search([('main_table', '=', True)])
        models = edi_tables.mapped("model_id")
        return [(model.model, model.name) for model in models]

    def reset(self):
        """
        This method is used to reset state to 'Draft'.
        Author: DG
        """
        for record in self:
            if record.reference and record.edi_type == "Incoming":
                raise ValidationError("This EDI transaction already processed, you can't reset it.")
        self.write({"state": "Draft"})

    def process(self):
        """
        This method is used to process edi transactions. Based on incoming & outgoing type it will perform.
        If it's incoming, then create a record in Odoo from FTP file data.
        If it's outgoing, then create an XML file & export in FTP/SFTP.
        Author: DG
        """
        if not self.ftp_attachment_id:
            raise ValidationError("No any attachment data found.")

        # Process for incoming type transactions.
        if self.edi_config_table_id and self.edi_type == "Incoming":
            if not self.xml_content:
                raise ValidationError("XML Data is Required to create a Record.")
            try:
                python_dict = xmltodict.parse(self.xml_content)
            except Exception as e:
                raise ValidationError("Something wrong in XML content: \n {}".format(e))
            for header in (self.edi_config_table_id.xml_header or "").split("/"):
                if header in python_dict:
                    python_dict = python_dict[header]
            self._create_record_from_attachment(python_dict, self.edi_config_table_id)

        # Process for outgoing type transactions.
        elif self.edi_type == "Outgoing":
            if self.log_id:
                main_log_id = self.log_id
            else:
                main_log_id = self.env['log.book'].create_main_log(self.name)

            # Checked export server folder set or not.
            if not self.edi_config_table_id.export_ftp_folder:
                log_msg = "Please select Export file to FTP/SFTP Directory in EDI config table [{}]".format(
                    self.edi_config_table_id.name)
                _logger.warning(log_msg)
                self.env['log.book.lines'].create_log(log_msg, main_log_id, fault_operation=True)
                self.write({
                    'state': 'Failed',
                    'log_id': main_log_id.id
                })
                self.message_post(body=f"Please check log [{main_log_id.name}] for more details.")
                return

            # Checked export folder upload configuration/permission set or not.
            elif not self.edi_config_table_id.export_ftp_folder.upload_this:
                log_msg = "Please enable Upload configuration for your selected export FTP directory [{}]".format(
                    self.edi_config_table_id.export_ftp_folder.name)
                _logger.warning(log_msg)
                self.env['log.book.lines'].create_log(log_msg, main_log_id, fault_operation=True)
                self.write({
                    'state': 'Failed',
                    'log_id': main_log_id.id
                })
                self.message_post(body=f"Please check log [{main_log_id.name}] for more details.")
                return

            # Based on server type connects to that server.
            if self.edi_config_table_id.server_type == 'sftp':
                server_record = self.edi_config_table_id.export_ftp_folder.sftp_syncing_id
            else:
                server_record = self.edi_config_table_id.export_ftp_folder.ftp_syncing_id
            if not server_record:
                self.env['log.book.lines'].create_log("Please Create Server record.", main_log_id, fault_operation=True)
                self.write({
                    'state': 'Failed',
                    'log_id': main_log_id.id
                })
                self.message_post(body=f"Please check log [{main_log_id.name}] for more details.")
                return
            try:
                server = server_record.check_sftp_connection() if self.edi_config_table_id.server_type == 'sftp' else server_record.check_ftp_connection()
            except ConnectionResetError as error:
                _logger.warning("Error due to ConnectionResetError")
                self.env['log.book.lines'].create_log("Error due to ConnectionResetError => {}".format(error),
                                                      main_log_id, fault_operation=True)
                self.write({
                    'state': 'Failed',
                    'log_id': main_log_id.id
                })
                self.message_post(body=f"Please check log [{main_log_id.name}] for more details.")
                return

            # From XML content create xml file in tmp folder, from tmp export to specific server.
            file = self.name
            with open("/tmp/" + self.name, "w+") as fp:
                if self.xml_content:
                    fp.write(self.xml_content)
                fp.close()
            source = self.edi_config_table_id.export_ftp_folder.name.strip("/")
            try:
                if server:
                    if self.edi_config_table_id.server_type == 'ftp':
                        server.cwd(source)
                        server.storlines("STOR " + file, open(os.path.join("/tmp/", file), "rb"))
                        _logger.info("Uploaded: {} from {} ".format(file, "/tmp/"))
                    else:
                        server.chdir(self.edi_config_table_id.export_ftp_folder.name)
                        file_path = os.path.join("/tmp/", file)
                        with open(file_path, "rb") as file_obj:
                            server.putfo(file_obj, file)
                    os.remove("/tmp/" + file)
                    self.state = "Done"

                    # In processed record/records is_processed set as true.
                    if self.reference_data:
                        for key, value in self.reference_data.items():
                            for v in value:
                                rec = self.env[key].browse(v)
                                rec.x_is_processed = True
                    elif self.reference and len(self.reference) == 2:
                        model_name, record_id = self.reference.split(',')
                        record_id = int(record_id)
                        record = self.env[model_name].browse(record_id)
                        record.x_is_processed = True
                    else:
                         self.reference.x_is_processed = True
                else:
                    self.env['log.book.lines'].create_log("Something went wrong", main_log_id, fault_operation=True)
                    self.write({
                        'state': 'Failed',
                        'log_id': main_log_id.id
                    })
                    self.message_post(body=f"Please check log [{main_log_id.name}] for more details.")
            except Exception as e:
                self.env['log.book.lines'].create_log("Something went wrong => {}".format(e),
                                                      main_log_id, fault_operation=True)
                self.write({
                    'state': 'Failed',
                    'log_id': main_log_id.id
                })
                self.message_post(body=f"Please check log [{main_log_id.name}] for more details.")
            if main_log_id and not main_log_id.log_detail_ids:
                main_log_id.unlink()

    def _prepare_vals_from_attachment(self, odoo_line, line, mapped_field):
        """
        This method is used to prepare vals/dictionary for record creation (Import record from FTP to Odoo).
        Author: DG
        """
        vals_dict = {}
        log_msg = ""
        create_record = True
        if mapped_field.ttype == 'many2one':
            if odoo_line.field_of_m2o_field:
                domain = [(odoo_line.field_of_m2o_field.name, '=', line)]
            else:
                domain = [('name', '=', line)]
            matched_record_of_m2o = self.env[mapped_field.relation].search(domain, limit=1)
            if matched_record_of_m2o:
                vals_dict = {mapped_field.name: matched_record_of_m2o.id}
                return vals_dict, create_record, log_msg
            else:
                create_record = False
                log_msg = "Your [{}] field's value [{}] is not matched with Odoo records, so this particular row/record is skipped.".format(
                    odoo_line.xml_element, line)
                return vals_dict, create_record, log_msg

        # Vals prepared for many2many field
        elif mapped_field.ttype == 'many2many':
            m2m_values = line.split(',')
            m2m_values_list = []
            for m2m_val in m2m_values:
                matched_record_of_m2m = self.env[mapped_field.relation].search(
                    [('name', '=', m2m_val)], limit=1)
                if not matched_record_of_m2m:
                    create_record = False
                    log_msg = "Your [{}] field's value [{}] is not matched with Odoo records, so this particular row/record is skipped.".format(
                        odoo_line.xml_element, line)
                    return vals_dict, create_record, log_msg
                m2m_values_list.append(matched_record_of_m2m.id)
            vals_dict = {mapped_field.name: [(6, 0, m2m_values_list)]}
            return vals_dict, create_record, log_msg

        # Vals prepared for boolean type fields
        elif mapped_field.ttype == 'boolean':
            if line.lower() in ['yes', 'true', 'y', '1']:
                vals_dict = {mapped_field.name: True}
                return vals_dict, create_record, log_msg
            elif line.lower() in ['no', 'false', 'n', '0']:
                vals_dict = {mapped_field.name: False}
                return vals_dict, create_record, log_msg

        # Vals prepared for float type fields
        elif mapped_field.ttype in ['float', 'monetary']:
            vals_dict = {mapped_field.name: float(line.replace(',', '.'))}
            return vals_dict, create_record, log_msg

        # Vals prepared for integer type fields
        elif mapped_field.ttype == 'integer':
            vals_dict = {mapped_field.name: int(float(line.replace(',', '.')))}
            return vals_dict, create_record, log_msg

        # Vals prepared for date/datetime type fields
        elif mapped_field.ttype in ['date', 'datetime']:
            if isinstance(line, str):
                parsed_date = parser.parse(line, yearfirst=True, dayfirst=False)
                # Format the date object to yyyy-mm-dd
                if mapped_field.ttype == 'date':
                    line = parsed_date.strftime('%Y-%m-%d')
                # Format the datetime object to yyyy-mm-dd h-m-s
                elif mapped_field.ttype == 'datetime':
                    line = parsed_date.strftime('%Y-%m-%d %H:%M:%S')
            vals_dict = {mapped_field.name: line}
            return vals_dict, create_record, log_msg

        # Vals prepared for selection type fields
        elif mapped_field.ttype == 'selection':
            if line in mapped_field.selection_ids.mapped('value'):
                vals_dict = {mapped_field.name: line}
                return vals_dict, create_record, log_msg
            else:
                if line in mapped_field.selection_ids.mapped('name'):
                    selection_value = mapped_field.selection_ids.filtered(
                        lambda a: a.name == line).value
                    vals_dict = {mapped_field.name: selection_value}
                    return vals_dict, create_record, log_msg
                else:
                    create_record = False
                    log_msg = "Your [{}] field's value [{}] is not matched with Odoo records, so this particular row/record is skipped.".format(
                        odoo_line.xml_element, line)
                    return vals_dict, create_record, log_msg

        # Vals prepared for other type fields
        else:
            vals_dict = {mapped_field.name: line}
            return vals_dict, create_record, log_msg

    def _create_record_from_attachment(self, python_dict, mapping_edi_table):
        """
        This method is used to create records in configured model/table in config table from attachments/xml content.
        Author: DG
        """
        if python_dict and mapping_edi_table:
            if self.log_id:
                main_log_id = self.log_id
            else:
                main_log_id = self.env['log.book'].create_main_log(self.name)
            if mapping_edi_table.default_value:
                vals = safe_eval(mapping_edi_table.default_value)
            else:
                vals = {}

            # If EDI transaction's mapping table file type is multiple then we handled it through a separate method
            # because there are many records in one file.
            if mapping_edi_table.file_type == 'multiple' and mapping_edi_table.main_table:
                if mapping_edi_table.line_ids:
                    main_table_xml_element = mapping_edi_table.line_ids[0].xml_element
                    mapping_edi_table = mapping_edi_table.line_ids[0].sub_edi_config_table_id
                    return self._create_multiple_record_from_single_attachment(python_dict, mapping_edi_table,
                                                                               main_table_xml_element, main_log_id)
                else:
                    raise ValidationError("Please configure Mapping XML Elements with Fields in the EDI config table.")
            next_process_after_create = []
            create_record = True

            # Handled logic to search existing record from multiple values & prepare domain based in those values.
            existing_main_record = self.env[mapping_edi_table.model_id.model]
            if mapping_edi_table.search_record_from_this_value:
                search_values = mapping_edi_table.search_record_from_this_value.split(',')
                search_domain = []

                for value in search_values:
                    field_line = mapping_edi_table.line_ids.filtered(lambda line: line.xml_element == value.strip())
                    if field_line:
                        # Split search values if nested, so we can go through upto final element and get proper value from dict.
                        # example: brand/default_code
                        xml_path = value.strip().split("/")
                        nested_value = python_dict
                        for key in xml_path:
                            nested_value = nested_value.get(key, None)  # Get next level; if key missing, return None
                            if nested_value is None:
                                break
                        search_value = nested_value
                        if search_value:
                            search_domain.append((field_line[0].odoo_field.name, '=', search_value))
                if search_domain:
                    existing_main_record = self.env[mapping_edi_table.model_id.model].search(search_domain, limit=1)

            for odoo_line in mapping_edi_table.line_ids:
                element_exist_or_not_python_dict = python_dict
                for header in (odoo_line.xml_element or "").split("/"):
                    if header in element_exist_or_not_python_dict:
                        element_exist_or_not_python_dict = element_exist_or_not_python_dict[header]
                    else:
                        log_msg = "%s element not found" % (odoo_line.xml_element)
                        self.env['log.book.lines'].create_log(log_msg, main_log_id, fault_operation=True)
                        self.write({
                            'state': 'Failed',
                            'log_id': main_log_id.id
                        })
                        self.message_post(body=f"Please check log [{main_log_id.name}] for more details.")
                        continue
                line = python_dict
                for header in (odoo_line.xml_element or "").split("/"):
                    if header in line:
                        line = line[header]
                    else:
                        line = None

                # If translation is required, then from translation table find corresponding Odoo value.
                if line and mapping_edi_table.is_translation_required:
                    translation_record = self.env['translation.table'].sudo().search(
                        [('edi_config_table_id', '=', mapping_edi_table.id),
                         ('xml_element', '=', odoo_line.xml_element),
                         ('xml_value', '=', line)], limit=1)
                    if translation_record and translation_record.corresponding_odoo_value:
                        line = translation_record.corresponding_odoo_value
                else:
                    continue

                mapped_field = odoo_line.odoo_field
                try:
                    if mapped_field.ttype != 'one2many':
                        vals_dict, create_record, log_msg = self._prepare_vals_from_attachment(odoo_line, line,
                                                                                               mapped_field)
                        if create_record:
                            if vals_dict:
                                vals.update(vals_dict)
                        else:
                            # Value not matched with Odoo records then skip that row, not import that record.
                            self.env['log.book.lines'].create_log(log_msg, main_log_id, fault_operation=True)
                            self.write({
                                'state': 'Failed',
                                'log_id': main_log_id.id
                            })
                            self.message_post(body=f"Please check log [{main_log_id.name}] for more details.")
                            break
                    else:
                        sub_table_for_o2m = odoo_line.sub_edi_config_table_id
                        if not isinstance(line, list):
                            line = [line]
                        for value in line:
                            vals_for_o2m = {}
                            for o2m_field_line in sub_table_for_o2m.line_ids:
                                o2m_line = value
                                for header in (o2m_field_line.xml_element or "").split("/"):
                                    if header in o2m_line:
                                        o2m_line = o2m_line[header]
                                    else:
                                        o2m_line = None

                                # If translation is required, then from translation table find corresponding Odoo value.
                                if o2m_line and sub_table_for_o2m.is_translation_required:
                                    translation_record = self.env['translation.table'].sudo().search(
                                        [('edi_config_table_id', '=', sub_table_for_o2m.id),
                                         ('xml_element', '=', o2m_field_line.xml_element),
                                         ('xml_value', '=', o2m_line)], limit=1)
                                    if translation_record and translation_record.corresponding_odoo_value:
                                        o2m_line = translation_record.corresponding_odoo_value
                                else:
                                    continue
                                o2m_field = o2m_field_line.odoo_field
                                vals_dict, create_record, log_msg = self._prepare_vals_from_attachment(o2m_field_line,
                                                                                                       o2m_line,
                                                                                                       o2m_field)
                                if create_record:
                                    if vals_dict:
                                        vals_for_o2m.update(vals_dict)
                                else:
                                    self.env['log.book.lines'].create_log(log_msg, main_log_id, fault_operation=True)
                                    self.write({
                                        'state': 'Failed',
                                        'log_id': main_log_id.id
                                    })
                                    self.message_post(body=f"Please check log [{main_log_id.name}] for more details.")
                                    break
                            if not create_record:
                                break
                            if vals_for_o2m:
                                next_process_after_create.append((odoo_line, vals_for_o2m, sub_table_for_o2m))
                except Exception as e:
                    error_message = "Something went wrong! {}".format(e)
                    self.env['log.book.lines'].create_log(error_message, main_log_id, fault_operation=True)
                    self.write({
                        'state': 'Failed',
                        'log_id': main_log_id.id
                    })
                    self.message_post(body=f"Please check log [{main_log_id.name}] for more details.")
                if not create_record:
                    break
            if create_record:
                if not existing_main_record:
                    # In creating record adding x_is_processed value as true.
                    if 'x_is_processed' not in vals:
                        vals['x_is_processed'] = True
                    created_record = self.env[mapping_edi_table.model_id.model].create(vals)
                else:
                    existing_main_record.write(vals)
                    created_record = existing_main_record

                # Process for o2m values, which we processed after the creation of the main record.
                for o2m_main_line, o2m_field_value, sub_table in next_process_after_create:
                    o2m_vals = {}
                    if sub_table.default_value:
                        o2m_vals = safe_eval(sub_table.default_value)
                    o2m_vals.update(o2m_field_value)
                    o2m_vals.update({o2m_main_line.odoo_field.relation_field: created_record.id})
                    search_domain = [(key, '=', value) for key, value in o2m_vals.items()]
                    if sub_table.search_record_from_this_value:
                        search_values = sub_table.search_record_from_this_value.split(',')
                        for value in search_values:
                            field_line = sub_table.line_ids.filtered(lambda line: line.xml_element == value.strip())
                            if field_line:
                                # Split search values if nested, so we can go through upto final element and get proper value from dict.
                                # example: brand/default_code
                                xml_path = value.strip().split("/")
                                nested_value = python_dict
                                for key in xml_path:
                                    nested_value = nested_value.get(key, None)  # Get next level; if key missing, return None
                                    if nested_value is None:
                                        break
                                search_value = nested_value
                                if search_value:
                                    search_domain.append((field_line[0].odoo_field.name, '=', search_value))
                        existing_child_record = self.env[sub_table.model_id.model].search(search_domain)
                        if existing_child_record:
                            existing_child_record.write(o2m_vals)
                        else:
                            self.env[sub_table.model_id.model].create(o2m_vals)
                    else:
                        self.env[sub_table.model_id.model].create(o2m_vals)
                self.state = 'Done'
                self.reference = "%s,%s" % (created_record._name, created_record.id)
            self._cr.commit()
            if main_log_id and not main_log_id.log_detail_ids:
                main_log_id.unlink()

    def _create_multiple_record_from_single_attachment(self, python_dict, mapping_edi_table, main_table_xml_element,
                                                 main_log_id):
        """
        This method is used to create multiple records from a single attachment.
        Also inside it regarding stock.quant some customizations implemented.
        Author: DG
        """
        create_record = True

        inventory_location = self.env['stock.location']
        if mapping_edi_table.model_id.model == 'stock.quant' and mapping_edi_table.location_id:
            inventory_location = mapping_edi_table.location_id
        for header in (main_table_xml_element or "").split("/"):
            if header in python_dict:
                python_dict = python_dict[header]

        log_reasons = []
        if not isinstance(python_dict, list):
            python_dict = [python_dict]
        for item in python_dict:
            next_process_after_create = []
            vals = {}
            if mapping_edi_table.default_value:
                vals = safe_eval(mapping_edi_table.default_value)

            # Handled logic to search existing record from multiple values & prepare domain based in those values.
            existing_main_record = self.env[mapping_edi_table.model_id.model]
            if mapping_edi_table.search_record_from_this_value:
                search_values = mapping_edi_table.search_record_from_this_value.split(',')
                search_domain = []

                for value in search_values:
                    field_line = mapping_edi_table.line_ids.filtered(lambda line: line.xml_element == value.strip())
                    if field_line:
                        # Split search values if nested, so we can go through upto final element and get proper value from dict.
                        # example: brand/default_code
                        xml_path = value.strip().split("/")
                        nested_value = item
                        for key in xml_path:
                            nested_value = nested_value.get(key, None)  # Get next level; if key missing, return None
                            if nested_value is None:
                                break
                        search_value = nested_value
                        if search_value:
                            search_domain.append((field_line[0].odoo_field.name, '=', search_value))
                if inventory_location and mapping_edi_table.model_id.model == 'stock.quant' and not any(
                        condition[0] == 'location_id' for condition in search_domain):
                    search_domain.append(('location_id', '=', inventory_location.id))
                if search_domain:
                    existing_main_record = self.env[mapping_edi_table.model_id.model].sudo().search(search_domain, limit=1)

            for odoo_line in mapping_edi_table.line_ids:

                xml_path = odoo_line.xml_element.split("/")  # Split sub_directories into list items
                # Traverse the dictionary
                nested_value = item
                for key in xml_path:
                    nested_value = nested_value.get(key, None)  # Get next level; if key missing, return None
                    if nested_value is None:
                        break

                if nested_value is None:
                # if odoo_line.xml_element not in item:
                    log_msg = "%s element not found" % (odoo_line.xml_element)
                    self.env['log.book.lines'].create_log(log_msg, main_log_id, fault_operation=True)
                    self.write({
                        'log_id': main_log_id.id
                    })
                    log_reasons.append('Failed')
                    self.message_post(body=f"Please check log [{main_log_id.name}] for more details.")
                    continue

                line = nested_value

                # If translation is required, then from translation table find corresponding Odoo value.
                if line and mapping_edi_table.is_translation_required:
                    translation_record = self.env['translation.table'].sudo().search(
                        [('edi_config_table_id', '=', mapping_edi_table.id),
                         ('xml_element', '=', odoo_line.xml_element),
                         ('xml_value', '=', line)], limit=1)
                    if translation_record and translation_record.corresponding_odoo_value:
                        line = translation_record.corresponding_odoo_value
                else:
                    continue

                mapped_field = odoo_line.odoo_field
                try:
                    if mapped_field.ttype != 'one2many':
                        vals_dict, create_record, log_msg = self._prepare_vals_from_attachment(odoo_line, line,
                                                                                               mapped_field)
                        if create_record:
                            if vals_dict:
                                vals.update(vals_dict)
                        else:
                            # Value not matched with Odoo records then skip that row, not import that record.
                            self.env['log.book.lines'].create_log(log_msg, main_log_id, fault_operation=True)
                            self.write({
                                'log_id': main_log_id.id
                            })
                            log_reasons.append('Failed')
                            self.message_post(body=f"Please check log [{main_log_id.name}] for more details.")
                            break
                    else:
                        sub_table_for_o2m = odoo_line.sub_edi_config_table_id
                        if not isinstance(line, list):
                            line = [line]
                        for value in line:
                            vals_for_o2m = {}
                            for o2m_field_line in sub_table_for_o2m.line_ids:
                                o2m_line = value
                                for header in (o2m_field_line.xml_element or "").split("/"):
                                    if header in o2m_line:
                                        o2m_line = o2m_line[header]
                                    else:
                                        o2m_line = None

                                # If translation is required, then from translation table find corresponding Odoo value.
                                if o2m_line and sub_table_for_o2m.is_translation_required:
                                    translation_record = self.env['translation.table'].sudo().search(
                                        [('edi_config_table_id', '=', sub_table_for_o2m.id),
                                         ('xml_element', '=', o2m_field_line.xml_element),
                                         ('xml_value', '=', o2m_line)], limit=1)
                                    if translation_record and translation_record.corresponding_odoo_value:
                                        o2m_line = translation_record.corresponding_odoo_value
                                else:
                                    continue
                                o2m_field = o2m_field_line.odoo_field
                                vals_dict, create_record, log_msg = self._prepare_vals_from_attachment(o2m_field_line,
                                                                                                       o2m_line,
                                                                                                       o2m_field)
                                if create_record:
                                    if vals_dict:
                                        vals_for_o2m.update(vals_dict)
                                else:
                                    self.env['log.book.lines'].create_log(log_msg, main_log_id, fault_operation=True)
                                    self.write({
                                        'log_id': main_log_id.id
                                    })
                                    log_reasons.append('Failed')
                                    self.message_post(body=f"Please check log [{main_log_id.name}] for more details.")
                                    break
                            if not create_record:
                                break
                            if vals_for_o2m:
                                next_process_after_create.append((odoo_line, vals_for_o2m, sub_table_for_o2m))
                except Exception as e:
                    error_message = "Something went wrong! {}".format(e)
                    self.env['log.book.lines'].create_log(error_message, main_log_id, fault_operation=True)
                    self.write({
                        'log_id': main_log_id.id
                    })
                    log_reasons.append('Failed')
                    self.message_post(body=f"Please check log [{main_log_id.name}] for more details.")
                if not create_record:
                    break
            if create_record and vals:
                if not existing_main_record:
                    # If import records of stock quant then in vals adding location.
                    if inventory_location and mapping_edi_table.model_id.model == 'stock.quant':
                        if 'location_id' not in vals:
                            vals['location_id'] = inventory_location.id
                    # In creating record adding x_is_processed value as true.
                    if 'x_is_processed' not in vals:
                        vals['x_is_processed'] = True
                    created_record = self.env[mapping_edi_table.model_id.model].create(vals)
                else:
                    existing_main_record.write(vals)
                    created_record = existing_main_record
                # if inventory_location and mapping_edi_table.model_id.model == 'stock.quant':
                #    created_record.action_apply_inventory()

                # Process for o2m values, which we processed after the creation of the main record.
                for o2m_main_line, o2m_field_value, sub_table in next_process_after_create:
                    o2m_vals = {}
                    if sub_table.default_value:
                        o2m_vals = safe_eval(sub_table.default_value)
                    o2m_vals.update(o2m_field_value)
                    o2m_vals.update({o2m_main_line.odoo_field.relation_field: created_record.id})
                    search_domain = [(key, '=', value) for key, value in o2m_vals.items()]
                    if sub_table.search_record_from_this_value:
                        search_values = sub_table.search_record_from_this_value.split(',')
                        for value in search_values:
                            field_line = sub_table.line_ids.filtered(lambda line: line.xml_element == value.strip())
                            if field_line:
                                # Split search values if nested, so we can go through upto final element and get proper value from dict.
                                # example: brand/default_code
                                xml_path = value.strip().split("/")
                                nested_value = python_dict
                                for key in xml_path:
                                    nested_value = nested_value.get(key, None)  # Get next level; if key missing, return None
                                    if nested_value is None:
                                        break
                                search_value = nested_value
                                if search_value:
                                    search_domain.append((field_line[0].odoo_field.name, '=', search_value))
                        existing_child_record = self.env[sub_table.model_id.model].search(search_domain, limit=1)
                        if existing_child_record:
                            existing_child_record.write(o2m_vals)
                        else:
                            self.env[sub_table.model_id.model].create(o2m_vals)
                    else:
                        self.env[sub_table.model_id.model].create(o2m_vals)
                log_reasons.append('Done')
        if all(line == 'Done' for line in log_reasons):
            self.state = 'Done'
        elif all(line == 'Failed' for line in log_reasons):
            self.state = 'Failed'
        else:
            self.state = 'Partially_Done'
        self._cr.commit()
        if main_log_id and not main_log_id.log_detail_ids:
            main_log_id.unlink()

    def auto_process_edi_transactions(self):
        """
        This method is used to process EDI transactions automatically from scheduled action,
        process those records which are in 'Draft' state.
        Author: DG
        """
        to_be_process_transactions = self.search([('state', '=', 'Draft')])
        for rec in to_be_process_transactions:
            rec.process()

    def recompute_xml(self):
        """
        This is specifically for outgoing records.
        This method is used to recompute XML content when record goes into failed state.
        Author: DG
        """
        # If a file type is multiple, then we call separate method which created for multiple records execution.
        if self.file_type == 'multiple':
            multiple_records = None
            for key, value in self.reference_data.items():
                multiple_records = self.env[key].browse(value)
                if multiple_records:
                    break
            if multiple_records:
                self.edi_config_table_id.export_process_for_multiple_records(multiple_records, self)
        # For single type file.
        else:
            self.edi_config_table_id.export_process(self.reference, self)
