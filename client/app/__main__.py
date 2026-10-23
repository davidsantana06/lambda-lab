from chainlit.cli import run_chainlit
import os

if __name__ == "__main__":
    os.environ["CHAINLIT_HOST"] = "0.0.0.0"
    os.environ["CHAINLIT_PORT"] = "9002"
    run_chainlit(os.path.join(os.path.dirname(__file__), "controllers.py"))
