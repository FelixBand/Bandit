"""
Bandit Telemetry Flask Server
Receives and logs anonymized usage data from Bandit game launcher instances
"""

from flask import Flask, request, jsonify
import json
import os
from datetime import datetime
from pathlib import Path
import sys

app = Flask(__name__)

# Debug: Log all requests
@app.before_request
def log_request():
    print(f"[REQUEST] {request.method} {request.path} from {request.remote_addr}", file=sys.stderr)
    print(f"[HEADERS] {dict(request.headers)}", file=sys.stderr)
    if request.is_json:
        print(f"[BODY] {request.get_json()}", file=sys.stderr)

# Data storage directory
DATA_DIR = Path(__file__).parent / "telemetry_data"
DATA_DIR.mkdir(exist_ok=True)

EVENTS_LOG = DATA_DIR / "events.jsonl"  # JSON Lines format for easy streaming


def log_event(event_data):
    """Append event to JSONL log file"""
    event_data["timestamp"] = datetime.utcnow().strftime("%d-%m-%Y %H:%M:%S")
    with open(EVENTS_LOG, "a") as f:
        f.write(json.dumps(event_data) + "\n")
    print(f"[LOGGED] Event written to {EVENTS_LOG}: {event_data}", file=sys.stderr)


@app.route("/api/telemetry", methods=["POST"])
def receive_telemetry():
    """Receive telemetry event from Bandit client"""
    try:
        data = request.get_json()
        print(f"[TELEMETRY] Received data: {data}", file=sys.stderr)
        
        if not data:
            print(f"[ERROR] No JSON data received", file=sys.stderr)
            return jsonify({"error": "No JSON data"}), 400

        # Basic validation
        required_fields = ["event_type", "account_name", "username", "app_version", "os"]
        missing = [f for f in required_fields if f not in data]
        if missing:
            print(f"[ERROR] Missing required fields: {missing}", file=sys.stderr)
            return jsonify({"error": "Missing required fields"}), 400

        # Sanitize and validate
        event = {
            "event_type": str(data.get("event_type", "unknown"))[:50],
            "account_name": str(data.get("account_name", "unknown"))[:100],
            "username": str(data.get("username", "unknown"))[:50],
            "app_version": str(data.get("app_version", "unknown"))[:20],
            "os": str(data.get("os", "unknown"))[:20],
            "game_id": str(data.get("game_id", ""))[:100] if data.get("game_id") else None,
            "game_name": str(data.get("game_name", ""))[:100] if data.get("game_name") else None,
            "ip_address": request.remote_addr,
        }

        log_event(event)
        print(f"[SUCCESS] Telemetry event processed successfully", file=sys.stderr)
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"[ERROR] Error processing telemetry: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": str(e)}), 500


@app.route("/api/telemetry/stats", methods=["GET"])
def get_stats():
    """Get aggregate telemetry stats (for you to review)"""
    try:
        if not EVENTS_LOG.exists():
            return jsonify({"total_events": 0, "events_by_type": {}}), 200

        events_by_type = {}
        events_by_os = {}
        total_events = 0
        games_downloaded = set()
        unique_users = set()

        with open(EVENTS_LOG, "r") as f:
            for line in f:
                try:
                    event = json.loads(line)
                    total_events += 1
                    event_type = event.get("event_type")
                    events_by_type[event_type] = events_by_type.get(event_type, 0) + 1
                    os_name = event.get("os") or "unknown"
                    events_by_os[os_name] = events_by_os.get(os_name, 0) + 1
                    if event.get("game_id"):
                        games_downloaded.add(event.get("game_id"))
                    unique_users.add(event.get("username"))
                except:
                    pass

        return jsonify({
            "total_events": total_events,
            "events_by_type": events_by_type,
            "events_by_os": events_by_os,
            "unique_users": len(unique_users),
            "games_downloaded": len(games_downloaded),
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/telemetry/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "ok", "version": "1.0"}), 200


if __name__ == "__main__":
    print(f"Telemetry server starting...")
    print(f"Logging to: {EVENTS_LOG}")
    app.run(host="0.0.0.0", port=5001, debug=False)
