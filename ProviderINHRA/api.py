from flask import Flask, request, jsonify
from state import StateStore
from datetime import datetime

def create_app(store: StateStore) -> Flask:
    app = Flask(__name__)

    @app.post("/led/<int:bin_no>")
    def update_led(bin_no: int):
        data = request.get_json(force=True) or {}
        try:
            color = int(data.get("color", 0))
            mode = int(data.get("mode", 0))
            duration = int(data.get("duration", 0))  # время в секундах
            
            # Используем метод с таймером
            store.set_led_with_timeout(bin_no, color, mode, duration, source="api")
            
            response = {
                "status": "ok", 
                "bin": bin_no, 
                "color": color, 
                "mode": mode,
                "duration": duration
            }
            
            if duration > 0:
                response["auto_off_in_seconds"] = duration
                response["message"] = f"LED will turn off automatically after {duration} seconds"
            
            return jsonify(response)
            
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            # logger.exception(f"API error: {e}")
            return jsonify({"error": "bad payload"}), 400
        
    @app.get("/bin/<int:bin_no>")
    def get_bin_state(bin_no: int):
        snap = store.get_snapshot()

        if bin_no not in snap["bins"]:
            return jsonify({"error": "bin not found"}), 404

        bin_data = snap["bins"][bin_no]

        return jsonify({
            "status": "ok",
            "bin": bin_no,
            "sensor": {
                "bin": bin_no,
                "value": bin_data["sensor"]["value"]
            },
            "led": {
                "bin": bin_no,
                "color": bin_data["led"]["color"],
                "mode": bin_data["led"]["mode"]
            }
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