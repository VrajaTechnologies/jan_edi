import logging
import tempfile
import zipfile
import os
import base64
from datetime import datetime
from xml.etree import ElementTree as ET
from xml.etree.ElementTree import Element, SubElement, tostring
from werkzeug.datastructures import FileStorage
from odoo import http
from odoo.http import request
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

class CXMLController(http.Controller):

    @http.route('/cxml/receive', type='http', auth='public', methods=['POST'], csrf=False)
    def receive_cxml(self, **kwargs):
        _logger.info("Received cXML request")
        saved_records = []
        errors = []
        try:
            # Check for uploaded files first (multipart/form-data)
            if request.httprequest.files:
                _logger.info("Processing uploaded files")
                for key, f in request.httprequest.files.items():
                    #here key suggest the data is file or not and f suggest specific file
                    if not isinstance(f, FileStorage):
                        _logger.warning("Skipping non-FileStorage object for key: %s", key)
                        continue
                    _logger.info("Processing file: %s", f.filename)
                    file_data = f.read()

                    if not file_data:
                        _logger.error("Empty file content for: %s", f.filename)
                        errors.append(f"Empty file content: {f.filename}")
                        continue

                    if f.filename.lower().endswith('.zip'):
                        _logger.info("Processing ZIP file: %s", f.filename)
                        with tempfile.TemporaryDirectory() as tmpdir:
                            with zipfile.ZipFile(f, 'r') as zip_ref:
                                zip_ref.extractall(tmpdir)
                                for file_name in os.listdir(tmpdir):
                                    if file_name.lower().endswith('.xml'):
                                        _logger.info("Processing XML file from ZIP: %s", file_name)
                                        with open(os.path.join(tmpdir, file_name), 'rb') as xf:
                                            xml_str = xf.read().decode('utf-8', errors='ignore')
                                            if not xml_str.strip():
                                                _logger.error("Empty XML in ZIP file: %s", file_name)
                                                errors.append(f"Empty XML in ZIP: {file_name}")
                                                continue
                                            rec = self._process_xml(xml_str)
                                            saved_records.append(rec.id)
                    elif f.filename.lower().endswith('.xml'):
                        _logger.info("Processing XML file: %s", f.filename)
                        xml_str = file_data.decode('utf-8', errors='ignore')
                        if not xml_str.strip():
                            _logger.error("Empty XML file: %s", f.filename)
                            errors.append(f"Empty XML file: {f.filename}")
                            continue
                        rec = self._process_xml(xml_str)
                        saved_records.append(rec.id)
                    else:
                        _logger.warning("Unsupported file type: %s", f.filename)
                        errors.append(f"Unsupported file type: {f.filename}")

            # Check for raw XML in request body
            else:
                _logger.info("Processing raw XML from request body")
                body = request.httprequest.data.decode('utf-8', errors='ignore')
                if not body.strip():
                    _logger.error("Empty XML received in request body")
                    return request.make_response(
                        self._build_cxml_response(400, "Empty XML"),
                        headers=[('Content-Type', 'application/xml')],
                        status=400
                    )
                rec = self._process_xml(body)
                saved_records.append(rec.id)

        except Exception as e:
            _logger.exception("Error processing cXML request: %s", str(e))
            errors.append(str(e))
        if errors:
            _logger.error("Errors occurred: %s", "; ".join(errors))
            return request.make_response(
                self._build_cxml_response(500, "Errors: " + "; ".join(errors)),
                headers=[('Content-Type', 'application/xml')],
                status=500
            )
        else:
            _logger.info("Successfully stored %d record(s)", len(saved_records))
            return request.make_response(
                self._build_cxml_response(200, f"Authenticated and stored {len(saved_records)} record(s)"),
                headers=[('Content-Type', 'application/xml')],
                status=200
            )

    def _process_xml(self, xml_str):
        """Process XML data: verify credentials and store in edi.transactions."""
        _logger.info("Processing XML data, size: %s chars", len(xml_str))

        # Parse XML and extract credentials
        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError as e:
            _logger.error("Invalid XML: %s", str(e))
            raise ValueError(f"Invalid XML: {str(e)}")

        username = root.findtext('./Header/Sender/Credential/Identity')
        password = root.findtext('./Header/Sender/Credential/SharedSecret')
        _logger.info("Extracted credentials: username=%s", username)

        if not username or not password:
            _logger.error("Missing credentials in XML")
            raise ValueError("Missing credentials")

        # Verify username and password
        _logger.info("Verifying credentials for username=%s", username)
        user = request.env['res.users'].sudo().search([('login', '=', username)], limit=1)
        if not user:
            _logger.error("User not found: %s", username)
            raise ValidationError(f"User not found: {username}")

        # Authenticate against Odoo database
        try:
            uid = request.session.authenticate(request.db, username, password)
            if not uid:
                _logger.error("Authentication failed for username=%s", username)
                raise ValidationError("Invalid username/password")
            _logger.info("Authentication successful, user ID: %s", uid)
        except Exception as e:
            _logger.error("Authentication error: %s", str(e))
            raise ValidationError(f"Authentication error: {str(e)}")

        # Find EDI configuration
        from_identity = '/cxml/receive'
        http_route_config = request.env['http.route.mapping.table'].sudo().search([
            ('route_name', '=', from_identity)
        ], limit=1)
        if not http_route_config:
            _logger.warning("No HTTP Route configuration found for identity: %s, using default", from_identity)
            edi_config = request.env['http.route.mapping.table'].sudo().search([], limit=1)
            if not edi_config:
                _logger.error("No http route configuration found in http.route.mapping.table")
                raise ValueError("No Http Route Mapping Table configuration found in http.route.mapping.table")

        # Store in edi.transactions
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        name = f"Incoming_cXML_{timestamp}.xml"
        rec = request.env['edi.transactions'].sudo().create({
            'name': name,
            'xml_content': xml_str,
            'edi_config_table_id': http_route_config.edi_config_table_id.id,
            'edi_type':http_route_config.edi_config_table_id.edi_type
        })
        file_data = base64.b64encode(xml_str.encode('utf-8'))
        # --- Create ftp.attachment with nested ir.attachment ---
        ftp_attachment = request.env['ftp.attachment'].with_context(from_controller=True).sudo().create({
            'attachment_id': request.env['ir.attachment'].sudo().create({
                'name': name,
                'datas': file_data,
                'mimetype': 'application/xml',
                'res_model': 'edi.transactions',
                'res_id': rec.id,
            }).id,
            'file_content': xml_str,
        })

        # Link the attachment to the transaction
        rec.ftp_attachment_id = ftp_attachment.id
        _logger.info("Created EDI transaction record with ID: %s", rec.id)
        return rec

    def _build_cxml_response(self, status_code, status_text):
        """Build cXML Response according to spec."""
        _logger.info("Building cXML response: code=%s, text=%s", status_code, status_text)
        cxml = Element('cXML', {
            'timestamp': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
            'xml:lang': 'en',
            'payloadID': f"resp-{datetime.utcnow().timestamp()}"
        })
        response = SubElement(cxml, 'Response')
        SubElement(response, 'Status', code=str(status_code),
                   text="OK" if status_code == 200 else "Error").text = status_text
        return tostring(cxml, encoding='utf-8', xml_declaration=True)