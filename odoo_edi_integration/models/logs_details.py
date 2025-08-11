import datetime
from odoo import models, fields, api
from datetime import datetime, timedelta


class LogBook(models.Model):
    _name = "log.book"
    _description = "Log Book"
    _order = 'id desc'

    name = fields.Char(
        string="Name"
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company"
    )
    file_name = fields.Char(
        string="File Name"
    )
    log_detail_ids = fields.One2many(
        comodel_name='log.book.lines',
        inverse_name='log_id',
        string='Logs'
    )

    @api.model_create_multi
    def create(self, vals_list):
        """
        This method is used to provide sequence name & company in created record.
        Author: DG
        """
        for vals in vals_list:
            sequence = self.env.ref("odoo_edi_integration.seq_edi_log_main_log")
            name = sequence and sequence.next_by_id() or '/'
            company_id = self._context.get('company_id', self.env.user.company_id.id)
            if type(vals) == dict:
                vals.update({'name': name, 'company_id': company_id})
        return super(LogBook, self).create(vals_list)

    def auto_delete_log_message(self):
        """
        This method is used to auto delete log messages through cron process which are older than 13 days.
        Author: DG
        """
        for obj in self.search([('create_date', '<', datetime.now() - timedelta(days=13))]):
            obj.log_detail_ids.unlink()
            obj.unlink()

    def create_main_log(self, file_name):
        """
        This method is used to create log record.
        Author: DG
        """
        vals = {'file_name': file_name}
        log_id = self.create(vals)
        return log_id


class LogBookLines(models.Model):
    _name = "log.book.lines"
    _description = "Log Book Lines"
    _order = 'id desc'

    name = fields.Char(
        string="Name"
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company"
    )
    log_message = fields.Char(
        string="Message"
    )
    log_id = fields.Many2one(
        comodel_name='log.book',
        string='Main Log',
        ondelete="cascade"
    )
    fault_operation = fields.Boolean(
        string="Fault"
    )

    @api.model_create_multi
    def create(self, vals_list):
        """
        This method is used to provide sequence name & company in created record.
        Author: DG
        """
        for vals in vals_list:
            sequence = self.env.ref("odoo_edi_integration.seq_edi_log_logs_line")
            name = sequence and sequence.next_by_id() or '/'
            company_id = self._context.get('company_id', self.env.user.company_id.id)
            if type(vals) == dict:
                vals.update({'name': name, 'company_id': company_id})
        return super(LogBookLines, self).create(vals_list)

    def create_log(self, log_message, main_log, fault_operation=False):
        """
        This method is used to create log line record.
        Author: DG
        """
        vals = {
            'log_message': log_message,
            'log_id': main_log and main_log.id,
            'fault_operation': fault_operation
        }
        log_id = self.create(vals)
        return log_id
