import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { WmsCamera } from "./camera";
import { useScanner, beep } from "./scan_input";

export class WmsPicking extends Component {
    static template = "wms_barcode.Picking";
    static props = ["*"];

    static components = { WmsCamera };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.pickingId = this.props.action.params.picking_id;
        this.state = useState({ picking: null, ctx: {}, msg: "", ok: true, manual: "", camera: false });
        onWillStart(async () => {
            this.state.picking = await this.orm.call("stock.picking", "wms_picking_data", [[this.pickingId]]);
        });
        useScanner((code) => this.scan(code));
    }

    toggleCamera() {
        this.state.camera = !this.state.camera;
    }

    async scan(code) {
        const r = await this.orm.call("stock.picking", "wms_scan", [[this.pickingId], code, this.state.ctx]);
        beep(r.ok);
        this.state.ok = r.ok;
        this.state.msg = r.message;
        this.state.ctx = r.ctx || {};
        this.state.picking = r.picking;
    }

    async manualScan(ev) {
        if (ev.key === "Enter" && this.state.manual) {
            const code = this.state.manual;
            this.state.manual = "";
            await this.scan(code);
        }
    }

    clearContext() {
        this.state.ctx = {};
    }

    lineClass(l) {
        if (l.done > l.demand) return "wms-over";
        if (l.done === l.demand) return "wms-done";
        return l.done > 0 ? "wms-partial" : "";
    }

    async createWave() {
        const id = await this.orm.call("stock.picking", "wms_create_wave",
            [[this.pickingId], this.state.ctx.location_id || false]);
        this.action.doAction({
            type: "ir.actions.client",
            tag: "wms_barcode_batch",
            params: { batch_id: id },
            target: "fullscreen",
        });
    }

    async validate() {
        const res = await this.orm.call("stock.picking", "wms_validate", [[this.pickingId]]);
        if (res && res !== true) {
            return this.action.doAction(res);
        }
        this.action.doAction({ type: "ir.actions.client", tag: "wms_barcode_home", target: "fullscreen" });
    }

    close() {
        this.action.doAction({ type: "ir.actions.client", tag: "wms_barcode_home", target: "fullscreen" });
    }
}

registry.category("actions").add("wms_barcode_picking", WmsPicking);
