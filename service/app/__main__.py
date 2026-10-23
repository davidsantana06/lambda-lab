from fastapi import FastAPI
import uvicorn

from controllers import router
from database import create_tables


app = FastAPI()
app.include_router(router)


if __name__ == "__main__":
    create_tables()
    uvicorn.run(app, host="0.0.0.0", port=9000)
