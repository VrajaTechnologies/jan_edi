from odoo import models, fields


class IrCron(models.Model):
    _inherit = 'ir.cron'

    ftp_syncing_id = fields.Many2one(
        comodel_name='ftp.syncing',
        string='FTP',
        ondelete="cascade"
    )
    sftp_syncing_id = fields.Many2one(
        comodel_name='sftp.syncing',
        string='SFTP',
        ondelete="cascade"
    )
