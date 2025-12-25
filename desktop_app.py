import subprocess
import time
import socket
from pathlib import Path

def wait_for_port(host: str, port: int, timeout_seconds: int = 10) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False

def main():
    base_dir = Path(__file__).parent.resolve()
    venv_python = base_dir / ".venv" / "bin" / "python"
    python_exe = str(venv_python) if venv_python.exists() else "python3"

    log_path = base_dir / "server.log"
    log_file = log_path.open("ab")

    server_proc = subprocess.Popen(
        [python_exe, "server.py"],
        cwd=str(base_dir),
        stdout=log_file,
        stderr=log_file,
    )

    try:
        if not wait_for_port("127.0.0.1", 5050, timeout_seconds=12):
            server_proc.terminate()
            raise RuntimeError("Server did not start. Check server.log")

        import webview

        window = webview.create_window(
            "File Sorter XX",
            "http://127.0.0.1:5050",
            width=1100,
            height=720,
        )

        def on_closed():
            try:
                server_proc.terminate()
                server_proc.wait(timeout=3)
            except Exception:
                try:
                    server_proc.kill()
                except Exception:
                    pass

        window.events.closed += on_closed
        webview.start(debug=False)

    finally:
        try:
            if server_proc.poll() is None:
                server_proc.terminate()
                server_proc.wait(timeout=2)
        except Exception:
            try:
                server_proc.kill()
            except Exception:
                pass
        try:
            log_file.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
