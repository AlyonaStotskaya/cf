import re

from odoo import api, models

GS1_FIXED = {"00": 18, "01": 14, "02": 14, "11": 6, "13": 6, "15": 6, "17": 6}
GS1_VAR = {"10": 20, "21": 20, "37": 8, "30": 8}
GS1_PAREN = re.compile(r"\((\d{2,4})\)([^(]+)")


class WmsResolver(models.AbstractModel):
    _name = "wms.resolver"
    _description = "WMS barcode resolver"

    @api.model
    def parse_gs1(self, barcode):
        """Minimal GS1-128 parser (AI 01,10,17,21,37,30). Returns dict or {}."""
        out = {}
        if "(" in barcode:
            out = {ai: v.strip() for ai, v in GS1_PAREN.findall(barcode)}
        elif re.match(r"^\d{2}", barcode) and len(barcode) > 16 and barcode[:2] in ("01", "02"):
            s = barcode.replace("\x1d", "\x1d")
            i = 0
            while i < len(s):
                ai = s[i:i + 2]
                i += 2
                if ai in GS1_FIXED:
                    out[ai] = s[i:i + GS1_FIXED[ai]]
                    i += GS1_FIXED[ai]
                elif ai in GS1_VAR:
                    j = s.find("\x1d", i)
                    j = len(s) if j == -1 else j
                    out[ai] = s[i:j][:GS1_VAR[ai]]
                    i = j + 1
                else:
                    return {}
        return out

    @api.model
    def resolve(self, barcode):
        """Identify what a barcode is. Returns {'type': ..., 'record': rec, ...}."""
        barcode = (barcode or "").strip()
        env = self.env
        if not barcode:
            return {"type": "unknown"}

        gs1 = self.parse_gs1(barcode)
        if gs1.get("01"):
            gtin = gs1["01"]
            product = env["product.product"].search(
                ["|", ("barcode", "=", gtin), ("barcode", "=", gtin.lstrip("0"))], limit=1)
            if product:
                qty = float(gs1["37"]) if gs1.get("37") else 1.0
                return {"type": "product", "record": product, "qty": qty,
                        "lot_name": gs1.get("21") or gs1.get("10"),
                        "serial": bool(gs1.get("21"))}

        loc = env["stock.location"].search([("barcode", "=", barcode)], limit=1)
        if loc:
            return {"type": "location", "record": loc}

        product = env["product.product"].search([("barcode", "=", barcode)], limit=1)
        if product:
            return {"type": "product", "record": product, "qty": 1.0}

        packaging = env["product.packaging"].search([("barcode", "=", barcode)], limit=1)
        if packaging:
            return {"type": "product", "record": packaging.product_id,
                    "qty": packaging.qty, "packaging": packaging}

        package = env["stock.quant.package"].search([("name", "=", barcode)], limit=1)
        if package:
            return {"type": "package", "record": package}

        picking = env["stock.picking"].search([("name", "=", barcode)], limit=1)
        if picking:
            return {"type": "picking", "record": picking}

        lots = env["stock.lot"].search([("name", "=", barcode)])
        if lots:
            return {"type": "lot", "record": lots[:1], "lots": lots, "lot_name": barcode}

        return {"type": "unknown", "lot_name": barcode}
