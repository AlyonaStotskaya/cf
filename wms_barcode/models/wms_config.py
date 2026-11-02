from odoo import api, fields, models


class WmsConfig(models.Model):
    _name = "wms.config"
    _description = "WMS barcode settings"
    _rec_name = "company_id"

    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    lots_only_source = fields.Boolean(
        "Only lots from source location", default=True,
        help="Outgoing/internal: accept only lots that have stock in the source location.")
    show_description = fields.Boolean(
        "Show product description", default=True,
        help="Show the product picking description on transfer lines.")
    forbid_over_stock = fields.Boolean(
        "Forbid moving more than in stock", default=True,
        help="Internal transfers: refuse scans that exceed the on-hand quantity at the source.")
    inv_start_zero = fields.Boolean(
        "Start inventory count from zero", default=True,
        help="If off, the first scan adds to the current on-hand quantity.")
    inv_location_id = fields.Many2one(
        "stock.location", "Default inventory location", domain=[("usage", "=", "internal")])

    _company_uniq = models.Constraint("unique(company_id)", "One WMS configuration per company.")

    @api.model
    def get_config(self):
        cfg = self.sudo().search([("company_id", "=", self.env.company.id)], limit=1)
        return cfg or self.sudo().create({"company_id": self.env.company.id})
