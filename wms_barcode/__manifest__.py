{
    "name": "WMS Barcode (Community)",
    "version": "19.0.1.0.0",
    "category": "Inventory/Inventory",
    "summary": "Warehouse barcode scanning for Odoo 19 Community: receipts, picks, transfers",
    "depends": ["stock", "stock_picking_batch", "barcodes"],
    "data": [
        "security/ir.model.access.csv",
        "views/stock_picking_views.xml",
        "views/wms_scan_log_views.xml",
        "views/wms_config_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "wms_barcode/static/src/scss/wms.scss",
            "wms_barcode/static/src/js/*.js",
            "wms_barcode/static/src/xml/*.xml",
        ],
    },
    "license": "LGPL-3",
    "application": True,
    "installable": True,
}
