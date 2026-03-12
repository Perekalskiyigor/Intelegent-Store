from flask import Flask, request, jsonify
from state import StateStore

def create_app(store: StateStore) -> Flask:
    app = Flask(__name__)

    @app.post("/led/<int:bin_no>")
    def update_led(bin_no: int):
        data = request.get_json(force=True) or {}
        try:
            color = int(data.get("color", 0))
            mode  = int(data.get("mode", 0))
            store.set_led(bin_no, color, mode, source="api")
            return jsonify({"status": "ok", "bin": bin_no, "color": color, "mode": mode})
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
        except Exception:
            return jsonify({"error": "bad payload"}), 400

    @app.get("/sensor/<int:bin_no>")
    def get_sensor(bin_no: int):
        snap = store.get_snapshot()
        if bin_no not in snap["bins"]:
            return jsonify({"error": "bin not found"}), 404
        return jsonify({
            "status": "ok",
            "bin": bin_no,
            "value": snap["bins"][bin_no]["sensor"]["value"]
        })

    @app.get("/sensors")
    def get_all_sensors():
        snap = store.get_snapshot()
        items = {b: d["sensor"]["value"] for b, d in snap["bins"].items()}
        return jsonify({"status": "ok", "items": items})

    @app.get("/state")
    def state():
        return jsonify(store.get_snapshot())

    return app