"""Phase 0a spike: confirms api/*.py + public/ coexist on Vercel with zero
new dependencies, before any GDAL/rasterio risk is introduced. See the
"De-risk GDAL on Vercel" plan phase -- delete once phases 0b-0d have passed.
"""
from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/api/ping")
def ping():
    return jsonify({"ok": True, "phase": "0a"})
