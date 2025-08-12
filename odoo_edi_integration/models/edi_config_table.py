from odoo import models, fields, api
from odoo.tools.convert import safe_eval
from odoo.exceptions import ValidationError
from xml.etree import ElementTree as ET
from xml.dom.minidom import parseString
from ast import literal_eval
import base64
import logging

_logger = logging.getLogger(__name__)


def data2xml(d, name="data"):
    """
    This method is used to convert dict data into xml data.
    Author: DG
    """
    r = ET.Element(name)
    xml_data = buildxml(r, d)
    try:
        return ET.tostring(xml_data, encoding="utf-8", xml_declaration=True)
    except Exception:
        return ET.tostring(xml_data)


def buildxml(r, d):
    """
    This method is used to convert dict data into xml data.
    Author: DG
    """
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, (tuple, list)):
                for i in v:
                    s = ET.SubElement(r, k)
                    buildxml(s, i)
            else:
                s = ET.SubElement(r, k)
                buildxml(s, v)
    elif isinstance(d, tuple) or isinstance(d, list):
        for v in d:
            r.text = str(v)
    elif isinstance(d, str):
        r.text = d
    elif isinstance(d, bool):
        r.text = ""
    elif d is None:
        r.text = ""
    else:
        r.text = str(d)
    return r


class EDIConfigTable(models.Model):
    _name = 'edi.config.table'
    _description = "EDI Config Table"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = 'sequence'

    name = fields.Char(
        string="Name"
    )
    model_id = fields.Many2one(
        comodel_name='ir.model',
        string="Odoo Model",
        tracking=True
    )
    file_type = fields.Selection(
        selection=[('single', 'In one file one record'), ('multiple', 'In one file multiple records')],
        default="single",
        string="File Type",
        help="- If your XML file having single record then select single\n "
             "- If your XML file having multiple records then select multiple",
        tracking=True
    )
    location_id = fields.Many2one(
        comodel_name='stock.location',
        string='Inventory Location'
    )
    field_for_location_visible = fields.Boolean(
        default=False
    )
    search_record_from_this_value = fields.Char(
        string="Search record from this value",
        help="Set the XML element name(s) here. Use the provided value(s) to check if existing records are available. You can specify multiple XML elements, separated by commas."
    )
    line_ids = fields.One2many(
        comodel_name='edi.config.table.line',
        inverse_name='edi_config_table_id'
    )
    sequence = fields.Integer(
        help='Used to order Companies in the company switcher',
        default=10
    )
    xml_header = fields.Char(
        string="XML Header",
        tracking=True
    )
    multiple_records_element = fields.Char(
        string="Export Multiple Record's XML Element Name",
        help="When you export multiple records in one file at that time you need to provide XML element for those multiple records.",
        tracking=True
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company"
    )
    default_value = fields.Char(
        string="Default Value",
        help="Ability to set default values in EDI model mapping.",
        copy=False,
        tracking=True
    )
    edi_type = fields.Selection(
        selection=[('Incoming', 'Incoming'), ('Outgoing', 'Outgoing')],
        string="Type",
        tracking=True
    )
    main_table = fields.Boolean(
        string="Main Table",
        default=False,
        help="If Set True, then it is the main table and if not set, then it is a sub-table."
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Trading Partner',
        copy=False,
        tracking=True
    )
    server_type = fields.Selection(
        selection=[('sftp', 'SFTP'), ('ftp', 'FTP')],
        string="Server Type",
        help="From which server your file is synced."
    )
    export_ftp_folder = fields.Many2one(
        comodel_name="ftp.list",
        string="Export file to FTP/SFTP Directory",
        copy=False,
        domain="[('server_type','=',server_type)]",
        tracking=True
    )
    additional_search_domain = fields.Char(
        string='Add additional search domain',
        help='When you are exporting records, if you need additional filters then add as domain filter.\n'
             'You can add one or multiple domains for filter out records.',
        copy=False,
        tracking=True
    )
    is_translation_required = fields.Boolean(
        string='Is Translation Required?',
        copy=False,
        default=False,
        tracking=True
    )

    @api.model_create_multi
    def create(self, vals_list):
        """
        This method is used to create is_processed field in a respected model for which config table created.
        Author: DG
        """
        res = super(EDIConfigTable, self).create(vals_list)
        for rec in res:
            is_processed_exists = self.env['ir.model.fields'].search(
                [('model_id', '=', rec.model_id.id), ('name', '=', 'x_is_processed')])
            if not is_processed_exists:
                self.env['ir.model.fields'].create({
                    'ttype': 'boolean',
                    'model_id': self.env['ir.model']._get_id(rec.model_id.model),
                    'name': 'x_is_processed',
                    'field_description': 'Is Processed',
                    'readonly': True,
                    'state': 'manual',
                    'copied': False
                })
        return res

    def write(self, vals):
        res = super(EDIConfigTable, self).write(vals)
        is_processed_exists = self.env['ir.model.fields'].search(
            [('model_id', '=', self.model_id.id), ('name', '=', 'x_is_processed')])
        if not is_processed_exists:
            self.env['ir.model.fields'].create({
                'ttype': 'boolean',
                'model_id': self.env['ir.model']._get_id(self.model_id.model),
                'name': 'x_is_processed',
                'field_description': 'Is Processed',
                'readonly': True,
                'state': 'manual',
                'copied': False
            })
        return res

    @api.onchange('model_id')
    def onchange_model_id(self):
        self.field_for_location_visible = False
        if self.model_id.model == 'stock.quant':
            self.field_for_location_visible = True

    @api.onchange('server_type')
    def onchange_server_type(self):
        self.export_ftp_folder = False

    def _get_nested_dict_ref(self, data, key_path):
        """
        This method is used to return parent dict and final key if there is a concept of nested element.
        Author: DG
        """
        keys = key_path.split('/')
        for key in keys[:-1]:
            data = data.setdefault(key, {})
        return data, keys[-1]

    def _export_record_prepare_values(self, record):
        """
        This method is used to prepare vals for export record.
        Author: DG
        """
        self.ensure_one()
        if self.default_value:
            dict_vals = safe_eval(self.default_value)
        else:
            dict_vals = {}
        for line in self.line_ids:
            value = record[line.odoo_field.name]
            value_to_update = dict_vals
            line_field = line.xml_element

            # If there is a nested element, then handled that thing.
            parent_dict, final_key = self._get_nested_dict_ref(value_to_update, line_field)

            if line.odoo_field.ttype in ["char", "text", "html", "selection"]:
                if value and line.char_length:
                    value = value[0: line.char_length]
                parent_dict[final_key] = value or ""

            elif line.odoo_field.ttype in ["boolean", "float", "monetary", "integer", ]:
                parent_dict[final_key] = str(value)

            elif line.odoo_field.ttype in ["date", "datetime"]:
                parent_dict[final_key] = value

            elif line.odoo_field.ttype == "many2one":
                if not value:
                    parent_dict[final_key] = ""
                elif line.field_of_m2o_field:
                    value = value[line.field_of_m2o_field.name]
                    parent_dict[final_key] = value or ""
                else:
                    parent_dict[final_key] = value['name']

            elif line.odoo_field.ttype in ("one2many", "many2many"):
                if not line.sub_edi_config_table_id:
                    raise ValidationError("Sub Config table is not setup for {}".format(line_field))
                list_vals = []
                for lv in value:
                    line_dict_vals = line.sub_edi_config_table_id._export_record_prepare_values(lv)
                    list_vals.append(line_dict_vals)
                parent_dict[final_key] = (list_vals[0] if len(list_vals) == 1 else list_vals)

            if line.required and not parent_dict.get(final_key):
                raise ValidationError("Required Value is not set for {}".format(line_field))

            if parent_dict.get(final_key) == {}:
                parent_dict[final_key] = None

        if not self._context.get('edi_multiple_record'):
            if not self.xml_header:
                return dict_vals
            headers = self.xml_header.split("/")
            for header in headers[::-1]:
                dict_vals = {header: dict_vals}
        return dict_vals

    def export_process(self, record, edi_transaction=False):
        """
        This method is specifically for single record in single file.
        This method is used to create FTP attachment, generate XML content & create edi transaction record if not there.
        Also using when need to recompute XML content if record goes into failed state.
        Author: DG
        """
        ftp_attachment_obj = self.env['ftp.attachment']
        edi_transaction_obj = self.env['edi.transactions']
        edi_partner = self.partner_id

        name = "%s_%s_%s.xml" % (
            record._table, record.id, record.display_name.replace("/", "_").replace(" ", "_")
        )
        if edi_transaction and edi_transaction.log_id:
            main_log_id = edi_transaction.log_id
        else:
            main_log_id = self.env['log.book'].create_main_log(name)
        xml_content = ftp_attachment = exception_info = False
        try:
            # Preparing dictionary from config table.
            dict_vals = self._export_record_prepare_values(record)

            # From dictionary convert into XML, then create/write attachment record.
            for key, values in dict_vals.items():
                xml_binary = data2xml(values, name=key)
                try:
                    dom = parseString(xml_binary)
                    xml_content = dom.toprettyxml(encoding="utf-8")
                except Exception:
                    xml_content = xml_binary
                attachment_data = base64.encodebytes(xml_content)
                res_model =  'sftp.syncing' if self.server_type == 'sftp' else 'ftp.syncing'
                attachment_value = {
                    "name": name,
                    "res_model": res_model,
                    "public": True,
                    "file_content": xml_content,
                    "datas": attachment_data,
                    "sync_date": fields.Datetime.now(),
                }
                ftp_attachment = ftp_attachment_obj.search(
                    [("name", "=", name)], limit=1
                )
                if not ftp_attachment:
                    ftp_attachment = ftp_attachment_obj.create(attachment_value)
                else:
                    ftp_attachment.write(attachment_value)
        except Exception as e:
            exception_info = e
            self.env['log.book.lines'].create_log("Something went wrong => {}".format(e), main_log_id,
                                                  fault_operation=True)
            _logger.info('Something went wrong at the time of preparing xml data => {}'.format(e))

        # Create/write EDI transaction record with all details.
        vals = {
            "name": name,
            "state": "Draft",
            "xml_content": xml_content,
            "edi_config_table_id": self.id,
            "edi_partner_id": edi_partner and edi_partner.id or False,
            "edi_type": "Outgoing",
            "reference": "%s,%s" % (record._name, record.id),
            "ftp_attachment_id": ftp_attachment and ftp_attachment.id or False,
        }
        if edi_transaction:
            edi_transaction.write(vals)
        else:
            edi_transaction = edi_transaction_obj.create(vals)
        if exception_info and edi_transaction:
            edi_transaction.write({
                'state': 'Failed',
                'log_id': main_log_id.id
            })
            edi_transaction.message_post(body=f"Please check log [{main_log_id.name}] for more details.")
            edi_transaction.message_post(
                body="After rectify issue, you can re-compute XML content again from 'Re-compute' button.")
        if main_log_id and not main_log_id.log_detail_ids:
            main_log_id.unlink()

    def export_edi_transactions(self):
        """
        This method is used through cronjob. It retrieves configuration records with EDI type 'Outgoing'
        and the main table flag enabled, then finds all related records from the specified model.
        Based on the configuration, it creates attachments and EDI transaction records.
        Author: DG
        """
        outgoing_config_tables = self.search([
            ('model_id.model', '!=', 'product.product'),
            ('edi_type', '=', 'Outgoing'),
            ('main_table', '=', True)
        ])

        for rec in outgoing_config_tables:
            edi_partner = rec.partner_id
            model = self.env[rec.model_id.model]

            # Base domain
            base_domain = [
                ('partner_id', 'child_of', edi_partner.id),
                ('x_is_processed', '=', False),
                ('company_id', '=', rec.company_id.id)
            ]

            # Attempt to parse additional domain from field
            additional_domain = []
            if rec.additional_search_domain:
                try:
                    parsed_domain = literal_eval(rec.additional_search_domain)
                    if isinstance(parsed_domain, list):
                        additional_domain = parsed_domain
                except Exception as e:
                    _logger.warning(f"Failed to parse additional_search_domain: {e}")

            # Combine both base and additional domains
            complete_domain = base_domain + additional_domain

            # Validate each field in the domain
            valid_domain = []
            for condition in complete_domain:
                if not isinstance(condition, (list, tuple)) or not condition:
                    continue

                field_path = condition[0]
                current_model = model
                is_valid = True

                # Traverse nested fields (e.g., partner_id.country_id.code)
                for field_name in field_path.split('.'):
                    if field_name in current_model._fields:
                        field = current_model._fields[field_name]
                        if field.type in ['many2one', 'one2many', 'many2many']:
                            current_model = self.env[field.comodel_name]
                    else:
                        _logger.warning(
                            f"Ignored invalid field '{field_path}' in domain for model '{rec.model_id.model}'"
                        )
                        is_valid = False
                        break

                if is_valid:
                    valid_domain.append(condition)

            # Perform search with validated domain
            records_need_to_export = model.search(valid_domain)

            # Process records based on file type
            if rec.file_type == 'multiple':
                if records_need_to_export:
                    rec.export_process_for_multiple_records(records_need_to_export)
            else:
                for record in records_need_to_export:
                    rec.export_process(record)

    def export_process_for_multiple_records(self, records_need_to_export, edi_transaction=False):
        """
        This is specifically for multiple records export together in single file.
        This method is used to create FTP attachment, generate XML content & create edi transaction record if not there.
        Also using when need to recompute XML content if record goes into failed state.
        Author: DG
        """
        multiple_records_vals = {}
        ftp_attachment_obj = self.env['ftp.attachment']
        edi_transaction_obj = self.env['edi.transactions']
        edi_partner = self.partner_id

        name = "%s_%s.xml" % (
            self.model_id.model.replace(".", "_"), "_".join(map(str, records_need_to_export.ids))
        )
        if edi_transaction and edi_transaction.log_id:
            main_log_id = edi_transaction.log_id
        else:
            main_log_id = self.env['log.book'].create_main_log(name)
        xml_content = ftp_attachment = exception_info = False
        try:
            # Preparing dictionary from config table.
            multi_vals = []
            for record in records_need_to_export:
                dict_vals = self.with_context(edi_multiple_record=True)._export_record_prepare_values(record)
                multi_vals.append(dict_vals)
            multiple_records_vals[self.multiple_records_element] = (multi_vals[0] if len(multi_vals) == 1 else multi_vals)
            if not self.xml_header:
                return multiple_records_vals
            headers = self.xml_header.split("/")
            for header in headers[::-1]:
                multiple_records_vals = {header: multiple_records_vals}

        except Exception as e:
            exception_info = e
            self.env['log.book.lines'].create_log("Something went wrong => {}".format(e), main_log_id,
                                                  fault_operation=True)
            _logger.info('Something went wrong at the time of preparing xml data => {}'.format(e))

        # From dictionary convert into XML, then create/write attachment record.
        for key, values in multiple_records_vals.items():
            xml_binary = data2xml(values, name=key)
            try:
                dom = parseString(xml_binary)
                xml_content = dom.toprettyxml(encoding="utf-8")
            except Exception:
                xml_content = xml_binary
            attachment_data = base64.encodebytes(xml_content)
            res_model =  'sftp.syncing' if self.server_type == 'sftp' else 'ftp.syncing'
            attachment_value = {
                "name": name,
                "res_model": res_model,
                "public": True,
                "file_content": xml_content,
                "datas": attachment_data,
                "sync_date": fields.Datetime.now(),
            }
            ftp_attachment = ftp_attachment_obj.search(
                [("name", "=", name)], limit=1
            )
            if not ftp_attachment:
                ftp_attachment = ftp_attachment_obj.create(attachment_value)
            else:
                ftp_attachment.write(attachment_value)

        # Create/write EDI transaction record with all details.
        create_vals = {
            "name": name,
            "state": "Draft",
            "xml_content": xml_content,
            "edi_config_table_id": self.id,
            "edi_type": "Outgoing",
            "reference_data": {self.model_id.model: records_need_to_export.ids},
            "ftp_attachment_id": ftp_attachment and ftp_attachment.id or False,
        }
        if self.model_id.model != 'product.product':
            create_vals.update({
                "edi_partner_id": edi_partner and edi_partner.id or False,
            })
        if edi_transaction:
            edi_transaction.write(create_vals)
        else:
            edi_transaction = edi_transaction_obj.create(create_vals)
        if exception_info and edi_transaction:
            edi_transaction.write({
                'state': 'Failed',
                'log_id': main_log_id.id
            })
            edi_transaction.message_post(body=f"Please check log [{main_log_id.name}] for more details.")
            edi_transaction.message_post(
                body="After rectify issue, you can re-compute XML content again from 'Re-compute' button.")
        if main_log_id and not main_log_id.log_detail_ids:
            main_log_id.unlink()
