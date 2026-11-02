import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { WmsCamera } from "./camera";
import { useScanner, beep } from "./scan_input";

export class WmsBatch extends Component {
    static template = "wms_barcode.Batch";
    static components = { WmsCamera };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.batchId = this.props.action.params.batch_id;
        this.state = useState({ batch: null, ctx: {}, msg: "", ok: true, manual: "", camera: false });
        onWillStart(async () => {
            this.state.batch = await this.orm.call("stock.picking.batch", "wms_batch_data", [[this.batchId]]);
        });
        useScanner((code) => this.scan(code));
    }

    toggleCamera() {
        this.state.camera = !this.state.camera;
    }

    async scan(code) {
        const r = await this.orm.call("stock.picking.batch", "wms_scan", [[this.batchId], code, this.state.ctx]);
        beep(r.ok);
        this.state.ok = r.ok;
        this.state.msg = r.message;
        this.state.ctx = r.ctx || {};
        this.state.batch = r.batch || this.state.batch;
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

    async validate() {
        const res = await this.orm.call("stock.picking.batch", "wms_validate", [[this.batchId]]);
        if (res && res !== true) {
            return this.action.doAction(res);
        }
        this.close();
    }

    close() {
        this.action.doAction({ type: "ir.actions.client", tag: "wms_barcode_home", target: "fullscreen" });
    }
}

registry.category("actions").add("wms_barcode_batch", WmsBatch);
