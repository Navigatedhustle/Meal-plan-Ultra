
import os
from flask import Flask
from mealplanner.web.routes import bp as web_bp

def create_app():
    app = Flask(__name__)
    app.config.update(
        APP_NAME=os.environ.get("APP_NAME","Home Meal Planner"),
        ALLOWED_EMBED_DOMAIN=os.environ.get("ALLOWED_EMBED_DOMAIN")
    )
    app.register_blueprint(web_bp)
    return app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT","5000"))
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("DEV_DEBUG")), use_reloader=False, threaded=True)
