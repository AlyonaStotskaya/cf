from odoo import fields, models


class WmsScanLog(models.Model):
    _name = "wms.scan.log"
    _description = "WMS scan log"
    _order = "id desc"

    picking_id = fields.Many2one("stock.picking", ondelete="cascade", index=True)
    user_id = fields.Many2one("res.users", default=lambda s: s.env.user, required=True)
    barcode = fields.Char(required=True)
    result_type = fields.Char()
    ok = fields.Boolean()
    message = fields.Char()
