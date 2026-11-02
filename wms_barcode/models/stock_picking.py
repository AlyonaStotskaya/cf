from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def action_open_wms(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "wms_barcode_picking",
            "name": self.name,
            "params": {"picking_id": self.id},
            "target": "fullscreen",
        }

    # ------------------------------------------------------------------ data
    @api.model
    def wms_home_data(self):
        types = self.env["stock.picking.type"].search([("active", "=", True)])
        res = []
        for t in types:
            domain = [("picking_type_id", "=", t.id),
                      ("state", "in", ("assigned", "confirmed", "waiting"))]
            res.append({
                "id": t.id,
                "name": t.display_name,
                "code": t.code,
                "count": self.search_count(domain + [("state", "=", "assigned")]),
                "late": self.search_count(domain + [("scheduled_date", "<", fields.Datetime.now())]),
            })
        return res

    def wms_picking_data(self):
        self.ensure_one()
        lines = []
        cfg = self.env["wms.config"].get_config()
        for move in self.move_ids.filtered(lambda m: m.state != "cancel"):
            mls = move.move_line_ids
            lines.append({
                "id": move.id,
                "product_id": move.product_id.id,
                "product": move.product_id.display_name,
                "barcode": move.product_id.barcode or "",
                "tracking": move.product_id.tracking,
                "demand": move.product_uom_qty,
                "done": sum(mls.filtered("picked").mapped("quantity")),
                "reserved": sum(mls.mapped("quantity")),
                "uom": move.product_uom.display_name,
                "locations": sorted({(l.location_id.display_name) for l in mls}),
                "dest": sorted({(l.location_dest_id.display_name) for l in mls}),
                "description": (move.product_id.description_picking or "") if cfg.show_description else "",
                "lots": [l.lot_id.name or l.lot_name for l in mls
                         if (l.lot_id or l.lot_name) and l.picked],
            })
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "code": self.picking_type_id.code,
            "partner": self.partner_id.display_name or "",
            "origin": self.origin or "",
            "lines": lines,
        }

    @api.model
    def wms_open_by_barcode(self, barcode):
        res = self.env["wms.resolver"].resolve(barcode)
        if res["type"] == "picking":
            return res["record"].id
        return False

    @api.model
    def wms_list(self, picking_type_id):
        pickings = self.search([("picking_type_id", "=", picking_type_id),
                                ("state", "=", "assigned")], order="scheduled_date", limit=100)
        return [{"id": p.id, "name": p.name, "partner": p.partner_id.display_name or "",
                 "date": fields.Datetime.to_string(p.scheduled_date)} for p in pickings]

    # ------------------------------------------------------------------ scan
    def wms_scan(self, barcode, ctx=None):
        """Process one scan. ctx = {location_id, package_id, lot_name} kept by the client.
        Returns {ok, type, message, ctx, picking}."""
        self.ensure_one()
        ctx = dict(ctx or {})
        if self.state in ("done", "cancel"):
            raise UserError(_("Transfer %s is already closed.", self.name))
        try:
            result = self._wms_process(barcode, ctx)
            ok = True
        except UserError as e:
            result = {"type": "error", "message": e.args[0]}
            ok = False
        self.env["wms.scan.log"].create({
            "picking_id": self.id, "barcode": barcode, "ok": ok,
            "result_type": result.get("type"), "message": result.get("message"),
        })
        result.update(ok=ok, ctx=result.get("ctx", ctx), picking=self.wms_picking_data())
        return result

    def _wms_process(self, barcode, ctx):
        res = self.env["wms.resolver"].resolve(barcode)
        kind = res["type"]
        if kind == "location":
            loc = res["record"]
            ctx["location_id"] = loc.id
            ctx["location_name"] = loc.display_name
            return {"type": "location", "ctx": ctx,
                    "message": _("Location: %s", loc.display_name)}
        if kind == "package":
            return self._wms_scan_package(res["record"], ctx)
        if kind == "lot" or (kind == "unknown" and self._wms_awaiting_lot(ctx)):
            ctx["lot_name"] = res.get("lot_name") or barcode
            pending = ctx.get("pending_product")
            if pending:
                product = self.env["product.product"].browse(pending)
                return self._wms_scan_product({"record": product, "qty": 1.0}, ctx)
            return {"type": "lot", "ctx": ctx, "message": _("Lot/Serial: %s", ctx["lot_name"])}
        if kind == "product":
            return self._wms_scan_product(res, ctx)
        if kind == "picking":
            raise UserError(_("Barcode belongs to another transfer: %s", res["record"].name))
        raise UserError(_("Unknown barcode: %s", barcode))

    def _wms_awaiting_lot(self, ctx):
        return bool(ctx.get("await_lot"))

    def _wms_scan_package(self, package, ctx):
        code = self.picking_type_id.code
        mls = self.move_line_ids.filtered(lambda l: l.picked and not l.result_package_id)
        if code in ("incoming", "internal"):
            mls.result_package_id = package
            ctx["package_id"] = package.id
            return {"type": "package", "ctx": ctx,
                    "message": _("Package %s assigned to %s lines", package.name, len(mls))}
        # outgoing: scanning a package picks its whole content for matching lines
        n = 0
        for ml in self.move_line_ids.filtered(lambda l: l.package_id == package):
            ml.picked = True
            n += 1
        if not n:
            raise UserError(_("Package %s is not in this transfer.", package.name))
        return {"type": "package", "ctx": ctx, "message": _("Package %s picked", package.name)}

    def _wms_scan_product(self, res, ctx):
        product, qty = res["record"], res.get("qty", 1.0)
        moves = self.move_ids.filtered(lambda m: m.product_id == product and m.state != "cancel")
        if not moves:
            raise UserError(_("%s is not part of this transfer.", product.display_name))

        lot_name = res.get("lot_name") or ctx.pop("lot_name", None)
        if product.tracking != "none" and not lot_name:
            ctx["await_lot"] = True
            ctx["pending_product"] = product.id
            return {"type": "need_lot", "ctx": ctx,
                    "message": _("Scan lot/serial for %s", product.display_name)}
        ctx.pop("await_lot", None)
        ctx.pop("pending_product", None)
        if product.tracking == "serial":
            qty = 1.0

        code = self.picking_type_id.code
        loc_id = ctx.get("location_id")
        line = self._wms_find_line(moves, product, lot_name, loc_id)
        uom_prec = product.uom_id.rounding

        if line:
            if product.tracking == "serial" and line.picked and line.quantity >= 1:
                raise UserError(_("Serial %s already scanned.", lot_name))
            new_qty = line.quantity + qty if line.picked else qty
            line.write({"quantity": new_qty, "picked": True})
        else:
            move = moves[0]
            vals = {
                "move_id": move.id, "picking_id": self.id, "product_id": product.id,
                "product_uom_id": move.product_uom.id, "quantity": qty, "picked": True,
                "location_id": move.location_id.id, "location_dest_id": move.location_dest_id.id,
            }
            if code == "outgoing" or code == "internal":
                vals["location_id"] = loc_id or move.location_id.id
            if code in ("incoming", "internal") and loc_id and code == "incoming":
                vals["location_dest_id"] = loc_id
            line = self.env["stock.move.line"].create(vals)

        if lot_name:
            self._wms_apply_lot(line, product, lot_name)
        if ctx.get("package_id") and code in ("incoming", "internal"):
            line.result_package_id = ctx["package_id"]
        if code == "incoming" and loc_id:
            line.location_dest_id = loc_id

        cfg = self.env["wms.config"].get_config()
        if code == "internal" and cfg.forbid_over_stock:
            on_hand = sum(self.env["stock.quant"].search([
                ("product_id", "=", product.id), ("location_id", "child_of", line.location_id.id),
                ("lot_id", "=", line.lot_id.id or False)]).mapped("quantity"))
            picked = sum(self.move_line_ids.filtered(lambda l: l.picked and l.product_id == product
                         and l.location_id == line.location_id
                         and l.lot_id == line.lot_id).mapped("quantity"))
            if float_compare(picked, on_hand, precision_rounding=uom_prec) > 0:
                line.quantity -= qty
                if float_is_zero(line.quantity, precision_rounding=uom_prec):
                    line.picked = False
                raise UserError(_("Only %s of %s in stock at %s.", on_hand,
                                  product.display_name, line.location_id.display_name))

        warning = ""
        done = sum(moves.move_line_ids.filtered("picked").mapped("quantity"))
        demand = sum(moves.mapped("product_uom_qty"))
        if float_compare(done, demand, precision_rounding=uom_prec) > 0:
            if code == "outgoing":
                line.quantity -= qty
                if float_is_zero(line.quantity, precision_rounding=uom_prec):
                    line.picked = False
                raise UserError(_("Quantity exceeds demand for %s.", product.display_name))
            warning = _(" (over demand)")
        return {"type": "product", "ctx": ctx,
                "message": _("%s +%s%s", product.display_name, qty, warning)}

    def _wms_find_line(self, moves, product, lot_name, loc_id):
        lines = moves.move_line_ids
        if lot_name:
            lines = lines.filtered(lambda l: (l.lot_id.name or l.lot_name) == lot_name) or \
                lines.filtered(lambda l: not l.lot_id and not l.lot_name)
        if loc_id and self.picking_type_id.code != "incoming":
            lines = lines.filtered(lambda l: l.location_id.id == loc_id)
        # prefer not yet picked lines, then partially picked
        unpicked = lines.filtered(lambda l: not l.picked)
        if unpicked:
            return unpicked[0]
        for l in lines:
            if l.quantity < l.move_id.product_uom_qty or self.picking_type_id.code == "incoming":
                return l
        return lines[:1] if lines else self.env["stock.move.line"]

    def _wms_apply_lot(self, line, product, lot_name):
        lot = self.env["stock.lot"].search([
            ("name", "=", lot_name), ("product_id", "=", product.id),
            ("company_id", "=", self.company_id.id)], limit=1)
        if lot:
            if self.env["wms.config"].get_config().lots_only_source and \
                    self.picking_type_id.code != "incoming":
                qty = sum(self.env["stock.quant"].search([
                    ("lot_id", "=", lot.id),
                    ("location_id", "child_of", line.location_id.id)]).mapped("quantity"))
                if qty <= 0:
                    raise UserError(_("Lot %s has no stock in %s.", lot_name,
                                      line.location_id.display_name))
            line.lot_id = lot
        elif self.picking_type_id.use_create_lots:
            line.lot_name = lot_name
        else:
            raise UserError(_("Lot/Serial %s does not exist.", lot_name))

    def wms_create_wave(self, location_id=False):
        """Create a wave from not-yet-picked lines (optionally only from one zone)."""
        self.ensure_one()
        lines = self.move_line_ids.filtered(lambda l: not l.picked)
        if location_id:
            loc = self.env["stock.location"].browse(location_id)
            lines = lines.filtered(lambda l: l.location_id.parent_path.startswith(loc.parent_path))
        if not lines:
            raise UserError(_("No lines to put in a wave."))
        if hasattr(lines, "_add_to_wave"):
            action = lines._add_to_wave()
            wave = self.env["stock.picking.batch"].search([("is_wave", "=", True)],
                                                           order="id desc", limit=1)
        else:
            wave = self.env["stock.picking.batch"].create({
                "is_wave": True, "picking_ids": [(6, 0, lines.picking_id.ids)],
                "picking_type_id": self.picking_type_id.id,
                "company_id": self.company_id.id})
        return wave.id

    def wms_validate(self):
        self.ensure_one()
        if not self.move_line_ids.filtered("picked"):
            raise UserError(_("Nothing scanned yet."))
        return self.button_validate()
