from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockPickingBatch(models.Model):
    _inherit = "stock.picking.batch"

    def action_open_wms(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client", "tag": "wms_barcode_batch", "name": self.name,
            "params": {"batch_id": self.id}, "target": "fullscreen",
        }

    # ------------------------------------------------------------- lists
    @api.model
    def wms_list(self, is_wave=False):
        batches = self.search([("state", "in", ("draft", "in_progress")),
                               ("is_wave", "=", bool(is_wave))], order="id desc", limit=100)
        return [{"id": b.id, "name": b.name, "user": b.user_id.display_name or "",
                 "count": len(b.picking_ids), "state": b.state} for b in batches]

    @api.model
    def wms_home_counts(self):
        dom = [("state", "in", ("draft", "in_progress"))]
        return {"batch": self.search_count(dom + [("is_wave", "=", False)]),
                "wave": self.search_count(dom + [("is_wave", "=", True)])}

    # -------------------------------------------------------------- data
    def wms_batch_data(self):
        """Aggregated pick list over all transfers of the batch, sorted by location."""
        self.ensure_one()
        agg = {}
        for picking in self.picking_ids:
            for line in picking.wms_picking_data()["lines"]:
                a = agg.setdefault(line["product_id"], dict(line, id=line["product_id"],
                                                            locations=set(), dest=set(),
                                                            lots=[], demand=0.0, done=0.0,
                                                            reserved=0.0, pickings=[]))
                a["demand"] += line["demand"]
                a["done"] += line["done"]
                a["reserved"] += line["reserved"]
                a["locations"] |= set(line["locations"])
                a["dest"] |= set(line["dest"])
                a["lots"] += line["lots"]
                a["pickings"].append(picking.name)
        lines = []
        for a in agg.values():
            a["locations"] = sorted(a["locations"])
            a["dest"] = sorted(a["dest"])
            lines.append(a)
        lines.sort(key=lambda a: (a["locations"][0] if a["locations"] else "", a["product"]))
        return {
            "id": self.id, "name": self.name, "state": self.state, "is_wave": self.is_wave,
            "user": self.user_id.display_name or "",
            "pickings": self.picking_ids.mapped("name"),
            "code": self.picking_type_id.code or (self.picking_ids[:1].picking_type_id.code),
            "lines": lines,
        }

    # -------------------------------------------------------------- scan
    def wms_scan(self, barcode, ctx=None):
        self.ensure_one()
        ctx = dict(ctx or {})
        if self.state in ("done", "cancel"):
            raise UserError(_("%s is already closed.", self.name))
        if self.state == "draft":
            self.action_confirm()
        try:
            result = self._wms_batch_process(barcode, ctx)
            ok = True
        except UserError as e:
            result, ok = {"type": "error", "message": e.args[0]}, False
        self.env["wms.scan.log"].create({
            "barcode": barcode, "ok": ok, "result_type": result.get("type"),
            "message": "[%s] %s" % (self.name, result.get("message", "")),
        })
        result.update(ok=ok, ctx=result.get("ctx", ctx), batch=self.wms_batch_data())
        return result

    def _wms_batch_process(self, barcode, ctx):
        res = self.env["wms.resolver"].resolve(barcode)
        kind = res["type"]
        pickings = self.picking_ids.filtered(lambda p: p.state not in ("done", "cancel"))
        if not pickings:
            raise UserError(_("No open transfers in %s.", self.name))
        if kind == "location":
            loc = res["record"]
            ctx.update(location_id=loc.id, location_name=loc.display_name)
            return {"type": "location", "ctx": ctx, "message": _("Location: %s", loc.display_name)}
        if kind == "package":
            done = 0
            for p in pickings:
                try:
                    p._wms_scan_package(res["record"], ctx)
                    done += 1
                except UserError:
                    continue
            if not done:
                raise UserError(_("Package %s not found in this batch.", res["record"].name))
            ctx["package_id"] = res["record"].id
            return {"type": "package", "ctx": ctx, "message": _("Package %s", res["record"].name)}
        if kind == "lot" or (kind == "unknown" and ctx.get("await_lot")):
            ctx["lot_name"] = res.get("lot_name") or barcode
            if ctx.get("pending_product"):
                product = self.env["product.product"].browse(ctx["pending_product"])
                return self._wms_batch_product(pickings, product, 1.0, {}, ctx)
            return {"type": "lot", "ctx": ctx, "message": _("Lot/Serial: %s", ctx["lot_name"])}
        if kind == "product":
            return self._wms_batch_product(pickings, res["record"], res.get("qty", 1.0), res, ctx)
        raise UserError(_("Unknown barcode: %s", barcode))

    def _wms_batch_product(self, pickings, product, qty, res, ctx):
        lot_name = res.get("lot_name") or ctx.get("lot_name")
        if product.tracking != "none" and not lot_name:
            ctx.update(await_lot=True, pending_product=product.id)
            return {"type": "need_lot", "ctx": ctx,
                    "message": _("Scan lot/serial for %s", product.display_name)}
        if product.tracking == "serial":
            qty = 1.0
        ordered = pickings.sorted(lambda p: (-int(p.priority or 0), p.id))
        left, last = qty, None
        for p in ordered:
            moves = p.move_ids.filtered(lambda m: m.product_id == product and m.state != "cancel")
            if not moves:
                continue
            remaining = sum(moves.mapped("product_uom_qty")) - sum(
                moves.move_line_ids.filtered("picked").mapped("quantity"))
            if remaining <= 0:
                continue
            take = min(remaining, left)
            sub_ctx = dict(ctx, lot_name=lot_name) if lot_name else dict(ctx)
            last = p._wms_scan_product({"record": product, "qty": take, "lot_name": lot_name}, sub_ctx)
            ctx = {k: v for k, v in last.get("ctx", ctx).items() if k != "lot_name"}
            left -= take
            if left <= 0:
                break
        if last is None:
            candidates = ordered.filtered(lambda p: product in p.move_ids.product_id)
            if not candidates:
                raise UserError(_("%s is not part of this batch.", product.display_name))
            if candidates[0].picking_type_id.code == "outgoing":
                raise UserError(_("Quantity exceeds demand for %s.", product.display_name))
            last = candidates[0]._wms_scan_product(
                {"record": product, "qty": qty, "lot_name": lot_name}, dict(ctx))
            ctx = {k: v for k, v in last.get("ctx", ctx).items() if k != "lot_name"}
        ctx.pop("await_lot", None)
        ctx.pop("pending_product", None)
        return {"type": "product", "ctx": ctx, "message": _("%s +%s", product.display_name, qty)}

    def wms_validate(self):
        self.ensure_one()
        if not self.move_line_ids.filtered("picked"):
            raise UserError(_("Nothing scanned yet."))
        if self.state == "draft":
            self.action_confirm()
        return self.action_done()
