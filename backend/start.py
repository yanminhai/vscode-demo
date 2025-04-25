import uvicorn
from main import app

if __name__ == "__main__":
    try:
        print("Starting server on port 7001...")
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=7001,
            log_level="info"
        )
    except Exception as e:
        print(f"Error starting server: {str(e)}")
        input("Press Enter to exit...")
