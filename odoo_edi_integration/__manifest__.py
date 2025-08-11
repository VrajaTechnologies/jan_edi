{
    # App information
    'name': 'EDI Connector (FTP/SFTP Connector / XML File Format)',
    'version': '1.10.0', # v17
    'category': 'Purchases',
    'summary': """
    This module integrates with FTP/SFTP servers to retrieve folder structures and create file attachments, 
    allowing seamless file management within Odoo. It supports importing and exporting various data, 
    facilitating efficient data transfer to and from Odoo. 
    - The module connects with FTP servers to fetch folder structures and generate file attachments.
    - It enables smooth file management within Odoo.
    - It supports data import and export.
    - It enhances efficient data transfer to and from Odoo.
    EDI Integration
    Dropshipper EDI Integration in Odoo
    Dynamic File Format
    Import DropShip Order Export Product Catalog
    Connect FTP and SFTP server,XML Export
    Import Product Catalog from FTP to Odoo
    Export Dropship orders from Odoo to FTP
    This module is configured to enable automated document sending and receiving in XML format between an EDI platform and Odoo.
    Data transmission between partners can be done quickly, effectively, and error-free with the help of EDI shipping and EDI fulfillment.EDI Odoo Module,Odoo EDI Automation,Odoo EDI Sync,
    Odoo EDI Integration,EDI Workflow Integration,EDI Communication,Odoo EDI Solution,EDI Automation,
    """,
    'license': 'OPL-1',

    # Dependencies
    'depends': ['mail', 'base', 'stock'],

    # Views
    'data': [
        'security/ir.model.access.csv',
        'views/ir_cron.xml',
        'views/ftp_syncing_view.xml',
        'views/edi_config_table_view.xml',
        'views/edi_transactions_view.xml',
        'views/logs_details.xml',
        'views/ftp_list_view.xml',
        'views/sftp_syncing_view.xml',
        'views/ftp_attachment_view.xml',
        'wizard/edi_export_records_wizard.xml',
        'data/ir_cron.xml',
    ],

    "external_dependencies": {
        "python": ["xmltodict", "paramiko"],
    },

    # Odoo Store Specific
    'images': ['static/description/cover.gif'],

    # Author
    'author': 'Vraja Technologies',
    'website': 'http://www.vrajatechnologies.com',
    'maintainer': 'Vraja Technologies',

    # Technical
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'live_test_url': 'https://www.vrajatechnologies.com/contactus',
    'price': '499',
    'currency': 'EUR',
}
# version changelog
# 1.0.0 => Initial setup
# 1.3.0 (9-1-25) => Multiple search elements handle in an import process from config table. Import inventory handled.
# 1.4.0 (15-1-25) => Managed processed field values in edi transaction either it's incoming or outgoing.
# 1.5.0 (23-1-25) => Added feature of SFTP syncing, which works the same as FTP syncing.
# 1.6.0 (07-2-25) => Added feature that handles multiple records in single file when imported. Export multiple product feature added. Added feature while importing records at that time search mapping table using XML header.
# 1.7.0 (12-2-25) => Added feature that handles daily new file coming in some directory & still process in Odoo. with it set scheduled action for fetch inner files.
# 1.8.0 (13-3-25) => Added feature that handles split files if they are big or having too many records.
# 1.9.0 (25-4-25) => Added feature that handles nested element in export file process and export multiple records in single file.
# 1.10.0 (1-8-25) => Exporting Specific Records (Given filter)
