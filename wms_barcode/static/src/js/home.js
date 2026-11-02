import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useScanner, beep } from "./scan_input";

export class WmsHome extends Component {
    static template = "wms_barcode.Home";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ types: [], list: [], current: null, msg: "" });
        onWillStart(async () => {
            this.state.types = await this.orm.call("stock.picking", "wms_home_data", []);
        });
        useScanner((code) => this.onScan(code));
    }

    async onScan(code) {
        const id = await this.orm.call("stock.picking", "wms_open_by_barcode", [code]);
        if (id) {
            beep(true);
            this.openPicking(id);
        } else {
            beep(false);
            this.state.msg = `Unknown transfer barcode: ${code}`;
        }
    }

    async openType(type) {
        this.state.current = type;
        this.state.list = await this.orm.call("stock.picking", "wms_list", [type.id]);
    }

    openPicking(id) {
        this.action.doAction({
            type: "ir.actions.client",
            tag: "wms_barcode_picking",
            params: { picking_id: id },
            target: "fullscreen",
        });
    }

    openInventory() {
        this.action.doAction({ type: "ir.actions.client", tag: "wms_barcode_inventory", target: "fullscreen" });
    }

    back() {
        this.action.restore ? this.action.restore() : this.action.doAction("stock.action_picking_tree_all");
    }
}

registry.category("actions").add("wms_barcode_home", WmsHome);
