from odoo import _, api, models
from odoo.exceptions import UserError


class StockQuant(models.Model):
    _inherit = "stock.quant"

    @api.model
    def wms_inv_data(self, location_id):
        """Quants of a location (and children) with their counted state."""
        loc = self.env["stock.location"].browse(location_id)
        quants = self.search([("location_id", "child_of", loc.id)], order="product_id, lot_id")
        return {
            "location": loc.display_name,
            "location_id": loc.id,
            "lines": [{
                "id": q.id,
                "product": q.product_id.display_name,
                "lot": q.lot_id.name or "",
                "package": q.package_id.name or "",
                "location": q.location_id.display_name,
                "on_hand": q.quantity,
                "counted": q.inventory_quantity if q.inventory_quantity_set else None,
                "uom": q.product_uom_id.display_name,
            } for q in quants],
        }

    @api.model
    def wms_inv_scan(self, barcode, ctx=None):
        ctx = dict(ctx or {})
        try:
            res = self._wms_inv_process(barcode, ctx)
            ok = True
        except UserError as e:
            res, ok = {"type": "error", "message": e.args[0]}, False
        self.env["wms.scan.log"].create({
            "barcode": barcode, "ok": ok, "result_type": res.get("type"),
            "message": "[inventory] %s" % res.get("message", ""),
        })
        res["ctx"] = res.get("ctx", ctx)
        res["ok"] = ok
        if res["ctx"].get("location_id"):
            res["data"] = self.wms_inv_data(res["ctx"]["location_id"])
        return res

    def _wms_inv_process(self, barcode, ctx):
        r = self.env["wms.resolver"].resolve(barcode)
        kind = r["type"]
        if kind == "location":
            loc = r["record"]
            if loc.usage != "internal":
                raise UserError(_("%s is not an internal location.", loc.display_name))
            ctx.update(location_id=loc.id, location_name=loc.display_name)
            ctx.pop("await_lot", None)
            ctx.pop("pending_product", None)
            return {"type": "location", "ctx": ctx, "message": _("Location: %s", loc.display_name)}
        if not ctx.get("location_id"):
            default = self.env["wms.config"].get_config().inv_location_id
            if default:
                ctx.update(location_id=default.id, location_name=default.display_name)
            else:
                raise UserError(_("Scan a location first."))
        if kind == "package":
            ctx["package_id"] = r["record"].id
            return {"type": "package", "ctx": ctx, "message": _("Package: %s", r["record"].name)}
        if kind == "lot" or (kind == "unknown" and ctx.get("await_lot")):
            ctx["lot_name"] = r.get("lot_name") or barcode
            if ctx.get("pending_product"):
                product = self.env["product.product"].browse(ctx["pending_product"])
                return self._wms_inv_product(product, 1.0, ctx)
            return {"type": "lot", "ctx": ctx, "message": _("Lot/Serial: %s", ctx["lot_name"])}
        if kind == "product":
            if r.get("lot_name"):
                ctx["lot_name"] = r["lot_name"]
            return self._wms_inv_product(r["record"], r.get("qty", 1.0), ctx)
        raise UserError(_("Unknown barcode: %s", barcode))

    def _wms_inv_product(self, product, qty, ctx):
        lot_name = ctx.pop("lot_name", None)
        if product.tracking != "none" and not lot_name:
            ctx.update(await_lot=True, pending_product=product.id)
            return {"type": "need_lot", "ctx": ctx,
                    "message": _("Scan lot/serial for %s", product.display_name)}
        ctx.pop("await_lot", None)
        ctx.pop("pending_product", None)
        if product.tracking == "serial":
            qty = 1.0
        Quant = self.with_context(inventory_mode=True)
        lot = False
        if product.tracking != "none":
            lot = self.env["stock.lot"].search([
                ("name", "=", lot_name), ("product_id", "=", product.id)], limit=1)
            if not lot:
                lot = self.env["stock.lot"].create({
                    "name": lot_name, "product_id": product.id,
                    "company_id": self.env.company.id})
        domain = [("product_id", "=", product.id), ("location_id", "=", ctx["location_id"]),
                  ("lot_id", "=", lot.id if lot else False),
                  ("package_id", "=", ctx.get("package_id") or False)]
        quant = Quant.search(domain, limit=1)
        if quant:
            if product.tracking == "serial" and quant.inventory_quantity_set:
                raise UserError(_("Serial %s already counted.", lot_name))
            if quant.inventory_quantity_set:
                new = quant.inventory_quantity + qty
            elif self.env["wms.config"].get_config().inv_start_zero:
                new = qty
            else:
                new = quant.quantity + qty
            quant.write({"inventory_quantity": new, "inventory_quantity_set": True})
        else:
            Quant.create({
                "product_id": product.id, "location_id": ctx["location_id"],
                "lot_id": lot.id if lot else False,
                "package_id": ctx.get("package_id") or False,
                "inventory_quantity": qty,
            })
        return {"type": "product", "ctx": ctx, "message": _("%s +%s", product.display_name, qty)}

    @api.model
    def wms_inv_apply(self, location_id):
        quants = self.with_context(inventory_mode=True).search([
            ("location_id", "child_of", location_id), ("inventory_quantity_set", "=", True)])
        if not quants:
            raise UserError(_("Nothing counted yet."))
        return quants.action_apply_inventory()

    @api.model
    def wms_inv_reset(self, location_id):
        quants = self.with_context(inventory_mode=True).search([
            ("location_id", "child_of", location_id), ("inventory_quantity_set", "=", True)])
        quants.action_clear_inventory_quantity()
        return True
