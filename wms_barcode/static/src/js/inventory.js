import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useScanner, beep } from "./scan_input";

export class WmsInventory extends Component {
    static template = "wms_barcode.Inventory";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null, ctx: {}, msg: "Scan a location to start", ok: true, manual: "" });
        useScanner((code) => this.scan(code));
    }

    async scan(code) {
        const r = await this.orm.call("stock.quant", "wms_inv_scan", [code, this.state.ctx]);
        beep(r.ok);
        this.state.ok = r.ok;
        this.state.msg = r.message;
        this.state.ctx = r.ctx || {};
        if (r.data) {
            this.state.data = r.data;
        }
    }

    async manualScan(ev) {
        if (ev.key === "Enter" && this.state.manual) {
            const code = this.state.manual;
            this.state.manual = "";
            await this.scan(code);
        }
    }

    diff(l) {
        return l.counted === null ? "" : l.counted - l.on_hand;
    }

    async apply() {
        const res = await this.orm.call("stock.quant", "wms_inv_apply", [this.state.data.location_id]);
        if (res && res !== true) {
            return this.action.doAction(res);
        }
        await this.refresh("Inventory applied");
    }

    async reset() {
        await this.orm.call("stock.quant", "wms_inv_reset", [this.state.data.location_id]);
        await this.refresh("Counts cleared");
    }

    async refresh(msg) {
        this.state.data = await this.orm.call("stock.quant", "wms_inv_data", [this.state.data.location_id]);
        this.state.msg = msg;
        this.state.ok = true;
    }

    close() {
        this.action.doAction({ type: "ir.actions.client", tag: "wms_barcode_home", target: "fullscreen" });
    }
}

registry.category("actions").add("wms_barcode_inventory", WmsInventory);
