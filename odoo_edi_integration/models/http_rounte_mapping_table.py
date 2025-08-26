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


class HttpRouteMappingTable(models.Model):
    _name = 'http.route.mapping.table'
    _description = "Http Route Mapping Table"

    route_name = fields.Char(
        string='Route Name'
    )
    edi_config_table_id = fields.Many2one(
        comodel_name="edi.config.table",
        string="Mapping Table",
        required=True,
        ondelete="cascade"
    )