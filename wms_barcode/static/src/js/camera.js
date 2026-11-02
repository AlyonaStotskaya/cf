import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";

/** Camera scanner based on the browser BarcodeDetector API (HTTPS required). */
export class WmsCamera extends Component {
    static template = "wms_barcode.Camera";
    static props = { onScan: Function, onClose: Function };

    setup() {
        this.video = useRef("video");
        this.state = useState({ error: "" });
        this.stream = null;
        this.timer = null;
        this.last = { code: "", at: 0 };
        onMounted(() => this.start());
        onWillUnmount(() => this.stop());
    }

    static isSupported() {
        return "BarcodeDetector" in window && !!navigator.mediaDevices?.getUserMedia;
    }

    async start() {
        if (!WmsCamera.isSupported()) {
            this.state.error =
                "Camera scanning needs HTTPS and a browser with BarcodeDetector (Chrome/Edge on Android). " +
                "Use a hardware scanner or manual input instead.";
            return;
        }
        try {
            this.stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: { ideal: "environment" } },
            });
            this.video.el.srcObject = this.stream;
            await this.video.el.play();
            const detector = new window.BarcodeDetector();
            this.timer = setInterval(async () => {
                try {
                    const codes = await detector.detect(this.video.el);
                    if (codes.length) {
                        const code = codes[0].rawValue;
                        const now = Date.now();
                        if (code !== this.last.code || now - this.last.at > 1500) {
                            this.last = { code, at: now };
                            this.props.onScan(code);
                        }
                    }
                } catch {
                    /* frame not ready */
                }
            }, 250);
        } catch (e) {
            this.state.error = `Camera unavailable: ${e.message || e}`;
        }
    }

    stop() {
        clearInterval(this.timer);
        this.stream?.getTracks().forEach((t) => t.stop());
    }
}
