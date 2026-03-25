from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import os
from pathlib import Path

app = FastAPI()

# Enable CORS for the Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DASHBOARD_PUBLIC_DIR = Path(__file__).parent / "dashboard" / "public"

class ControlRequest(BaseModel):
    is_live: bool
    enabled: bool

@app.post("/api/control")
async def update_bot_status(req: ControlRequest):
    filename = "live_config.json" if req.is_live else "sim_config.json"
    file_path = DASHBOARD_PUBLIC_DIR / filename
    
    try:
        # Load existing config
        if file_path.exists():
            with open(file_path, "r") as f:
                config = json.load(f)
        else:
            config = {}
            
        # Update enabled status
        config["enabled"] = req.enabled
        
        # Write back
        with open(file_path, "w") as f:
            json.dump(config, f)
            
        # Also update .env for persistence if needed
        # (This is optional since the bots now read from config files)
            
        return {"status": "ok", "enabled": req.enabled}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
