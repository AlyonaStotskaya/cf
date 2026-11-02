import { onMounted, onWillUnmount } from "@odoo/owl";

/** Global scanner listener: scanners type fast and end with Enter. */
export function useScanner(onScan) {
    let buf = "";
    let last = 0;
    const handler = (ev) => {
        const t = ev.target;
        if (t && ["INPUT", "TEXTAREA"].includes(t.tagName) && !t.dataset.wmsScan) {
            return;
        }
        const now = Date.now();
        if (now - last > 100) {
            buf = "";
        }
        last = now;
        if (ev.key === "Enter") {
            if (buf.length > 2) {
                onScan(buf);
            }
            buf = "";
        } else if (ev.key.length === 1) {
            buf += ev.key;
        }
    };
    onMounted(() => document.addEventListener("keydown", handler));
    onWillUnmount(() => document.removeEventListener("keydown", handler));
}

export function beep(ok) {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const o = ctx.createOscillator();
        o.frequency.value = ok ? 880 : 220;
        o.connect(ctx.destination);
        o.start();
        o.stop(ctx.currentTime + (ok ? 0.08 : 0.35));
    } catch {
        /* no audio */
    }
}
