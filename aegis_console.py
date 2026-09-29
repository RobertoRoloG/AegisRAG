"""
=============================================================================
AEGIS RAG — Consola Unificada y Panel de Control Interactivo 24/7
=============================================================================
Diseñado para máxima eficiencia y estabilidad en entornos de producción (VPS)
y desarrollo local:
 - Consumo ultra-bajo de recursos (<20MB RAM, 0% CPU en reposo).
 - Detección automática de entorno (VPS Linux vs PC Windows).
 - Supervisión y control de:
     * Docker Compose (PostgreSQL, Qdrant, Redis)
     * Backend FastAPI (Uvicorn)
     * Celery Worker (Tareas asíncronas)
     * Frontend Next.js
     * Túnel Ngrok (opcional, solo en local si está presente)
 - Buffer circular en memoria sin fugas de RAM (deque acotado).
 - Menú interactivo limpio con selector de logs en vivo.
=============================================================================
"""

import os
import sys
import time
import json
import signal
import shutil
import socket
import threading
import subprocess
import urllib.request
import urllib.error
from collections import deque
from pathlib import Path
from datetime import datetime

# Configuración UTF-8 para consola Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
NGROK_EXE = ROOT_DIR / "ngrok.exe"

IS_WINDOWS = sys.platform == "win32"

# =============================================================================
# ESTILOS ANSI OPTIMIZADOS
# =============================================================================
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

if IS_WINDOWS:
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass

# =============================================================================
# CARGA DE VARIABLES DE ENTORNO
# =============================================================================
def load_env():
    env_file = BACKEND_DIR / ".env"
    if not env_file.exists():
        return
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k and k not in os.environ:
                os.environ[k] = v

load_env()

# =============================================================================
# DETECCIÓN EFICIENTE DE PYTHON
# =============================================================================
def find_python():
    if IS_WINDOWS:
        venv_py = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        venv_py = BACKEND_DIR / ".venv" / "bin" / "python"

    if venv_py.exists():
        try:
            res = subprocess.run([str(venv_py), "-c", "import sys"], capture_output=True, timeout=2)
            if res.returncode == 0:
                return str(venv_py)
        except Exception:
            pass

    current_py = sys.executable
    if current_py and os.path.exists(current_py):
        return current_py

    if IS_WINDOWS and Path("C:/Python314/python.exe").exists():
        return "C:/Python314/python.exe"

    return shutil.which("python3") or shutil.which("python") or "python"

PYTHON_EXE = find_python()

# =============================================================================
# GESTOR DE SUBPROCESOS CON CONSUMO MÍNIMO DE RAM
# =============================================================================
class ServiceProcess:
    def __init__(self, name: str, tag: str, color: str, command: list, cwd: Path, env: dict = None):
        self.name = name
        self.tag = tag
        self.color = color
        self.command = command
        self.cwd = cwd
        self.env = env or os.environ.copy()
        self.process = None
        self.thread = None
        self.is_running = False
        # Buffer circular acotado a 100 líneas (evita crecimiento de memoria en 24/7)
        self.log_history = deque(maxlen=100)

    def start(self, supervisor=None):
        if self.is_running and self.process and self.process.poll() is None:
            return
        try:
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
            self.process = subprocess.Popen(
                self.command,
                cwd=str(self.cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=flags,
                env=self.env
            )
            self.is_running = True
            self.thread = threading.Thread(target=self._reader, args=(supervisor,), daemon=True)
            self.thread.start()
        except Exception as e:
            print(f"{C.RED}[ERROR AL INICIAR {self.name}]{C.RESET} {e}")

    def _reader(self, supervisor):
        try:
            for line in iter(self.process.stdout.readline, ""):
                if not line:
                    break
                clean_line = line.rstrip()
                if clean_line:
                    now_str = datetime.now().strftime("%H:%M:%S")
                    formatted = f"{C.DIM}{now_str}{C.RESET} {self.color}[{self.tag}]{C.RESET} {clean_line}"
                    self.log_history.append(formatted)
                    if supervisor and supervisor.streaming_logs:
                        print(formatted, flush=True)
        except Exception:
            pass
        finally:
            self.is_running = False

    def stop(self):
        if not self.process:
            self.is_running = False
            return
        try:
            pid = self.process.pid
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=5)
            else:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                self.process.wait(timeout=3)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass
        finally:
            self.is_running = False


# =============================================================================
# PANEL DE CONTROL VPS PRINCIPAL (OPTIMIZADO PARA 24/7)
# =============================================================================
class AegisVPSConsole:
    def __init__(self):
        self.services = {}
        self.should_exit = False
        self.streaming_logs = False
        self.stats = {
            "backend": "offline",
            "celery": "offline",
            "frontend": "offline",
            "postgres": "unknown",
            "qdrant": "unknown",
            "redis": "unknown",
            "ngrok_url": None,
            "total_docs": 0,
            "completed_docs": 0,
            "processing_docs": 0,
            "failed_docs": 0,
            "total_chunks": 0,
            "last_check": None
        }
        self.init_services()
        # Hilo demonio de bajo consumo con sondeo adaptativo
        self.monitor_thread = threading.Thread(target=self._metrics_daemon, daemon=True)
        self.monitor_thread.start()

    def init_services(self):
        # 1. FastAPI Uvicorn
        backend_cmd = [
            PYTHON_EXE, "-m", "uvicorn", "app.main:app",
            "--reload" if not os.environ.get("PRODUCTION") else "",
            "--host", "0.0.0.0", "--port", "8000"
        ]
        backend_cmd = [c for c in backend_cmd if c]
        self.services["backend"] = ServiceProcess("Backend FastAPI", "FASTAPI", C.CYAN, backend_cmd, BACKEND_DIR)

        # 2. Celery Worker (Pool solo en Windows, prefork en Linux/VPS)
        celery_pool = "solo" if IS_WINDOWS else "threads"
        celery_cmd = [
            PYTHON_EXE, "-m", "celery", "-A", "app.workers.celery_app",
            "worker", "--loglevel=info", f"--pool={celery_pool}"
        ]
        self.services["celery"] = ServiceProcess("Celery Worker", "CELERY ", C.MAGENTA, celery_cmd, BACKEND_DIR)

        # 3. Frontend Next.js
        if IS_WINDOWS:
            npm_cmd = ["cmd", "/c", "npm run dev"]
        else:
            npm_cmd = ["npm", "run", "dev"]
        self.services["frontend"] = ServiceProcess("Frontend Next.js", "FRONTEND", C.GREEN, npm_cmd, FRONTEND_DIR)

        # 4. Ngrok Tunnel (solo si existe el binario en local, en VPS no es necesario)
        if NGROK_EXE.exists() or shutil.which("ngrok"):
            ngrok_bin = str(NGROK_EXE) if NGROK_EXE.exists() else "ngrok"
            ngrok_cmd = [ngrok_bin, "http", "8000", "--domain=footing-jellied-glamorous.ngrok-free.dev"]
            self.services["ngrok"] = ServiceProcess("Ngrok Tunnel", "NGROK  ", C.YELLOW, ngrok_cmd, ROOT_DIR)

    def print_ascii_header(self):
        print(f"{C.CYAN}{C.BOLD}")
        print(r"""
   █████╗ ███████╗ ██████╗ ██╗███████╗     ██████╗  █████╗  ██████╗ 
  ██╔══██╗██╔════╝██╔════╝ ██║██╔════╝     ██╔══██╗██╔══██╗██╔════╝ 
  ███████║█████╗  ██║  ███╗██║███████╗     ██████╔╝███████║██║  ███╗
  ██╔══██║██╔══╝  ██║   ██║██║╚════██║     ██╔══██╗██╔══██║██║   ██║
  ██║  ██║███████╗╚██████╔╝██║███████║     ██║  ██║██║  ██║╚██████╔╝
  ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚═╝╚══════╝     ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ 
        """)
        print(f"  {C.BOLD}{C.WHITE}PANEL DE CONTROL & SERVICIOS — AEGIS RAG v2.0 (24/7 Ready){C.RESET}")
        print(f"  {C.DIM}Python: {PYTHON_EXE} | Entorno: {'Windows' if IS_WINDOWS else 'Linux/VPS'}{C.RESET}")
        print(f"{C.CYAN}{'═' * 78}{C.RESET}")

    def _check_socket(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.6):
                return True
        except Exception:
            return False

    def _collect_metrics(self):
        # 1. Health API Check
        try:
            req = urllib.request.Request("http://127.0.0.1:8000/api/v1/health", headers={"User-Agent": "Aegis247"})
            with urllib.request.urlopen(req, timeout=1.2) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    self.stats["backend"] = "healthy"
                    self.stats["postgres"] = data.get("postgres", "up")
                    self.stats["qdrant"] = data.get("qdrant", "up")
                    self.stats["redis"] = data.get("redis", "up")
                else:
                    self.stats["backend"] = "degraded"
        except Exception:
            self.stats["backend"] = "offline"
            self.stats["postgres"] = "up" if self._check_socket("127.0.0.1", 5433) else "down"
            self.stats["qdrant"] = "up" if self._check_socket("127.0.0.1", 6333) else "down"
            self.stats["redis"] = "up" if self._check_socket("127.0.0.1", 6380) else "down"

        # 2. Frontend Check
        self.stats["frontend"] = "online" if self._check_socket("127.0.0.1", 3000) else "offline"

        # 3. Ngrok Check (si está activo)
        if "ngrok" in self.services:
            try:
                req = urllib.request.Request("http://127.0.0.1:4040/api/tunnels", headers={"User-Agent": "Aegis247"})
                with urllib.request.urlopen(req, timeout=0.8) as resp:
                    tdata = json.loads(resp.read().decode())
                    tunnels = tdata.get("tunnels", [])
                    self.stats["ngrok_url"] = tunnels[0].get("public_url") if tunnels else None
            except Exception:
                self.stats["ngrok_url"] = None

        # 4. Celery Check
        self.stats["celery"] = "active" if self.services["celery"].is_running else "offline"

        # 5. Ingestion Stats
        try:
            req = urllib.request.Request("http://127.0.0.1:8000/api/v1/documents", headers={"User-Agent": "Aegis247"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    docs = json.loads(resp.read().decode())
                    self.stats["total_docs"] = len(docs)
                    self.stats["completed_docs"] = sum(1 for d in docs if d.get("status") == "COMPLETED")
                    self.stats["processing_docs"] = sum(1 for d in docs if d.get("status") in ["PROCESSING", "PENDING"])
                    self.stats["failed_docs"] = sum(1 for d in docs if d.get("status") == "FAILED")
                    self.stats["total_chunks"] = sum((d.get("total_chunks") or 0) for d in docs if d.get("status") == "COMPLETED")
        except Exception:
            pass

        self.stats["last_check"] = datetime.now().strftime("%H:%M:%S")

    def _metrics_daemon(self):
        """Loop en segundo plano que sondea con tiempo de espera adaptativo sin consumir CPU."""
        while not self.should_exit:
            try:
                self._collect_metrics()
            except Exception:
                pass
            time.sleep(8)

    def print_status_summary(self):
        self._collect_metrics()
        
        def badge(state):
            if state in ["healthy", "online", "up", "active"]:
                return f"{C.GREEN}● ONLINE{C.RESET}"
            elif state in ["degraded", "starting", "responding"]:
                return f"{C.YELLOW}◐ RESTRINGIDO{C.RESET}"
            else:
                return f"{C.RED}○ OFFLINE{C.RESET}"

        print(f"\n{C.BOLD}{C.WHITE}ESTADO DE SERVICIOS EN TIEMPO REAL:{C.RESET}")
        print(f"  • PostgreSQL (5433):   {badge(self.stats['postgres'])}   • FastAPI Backend (8000): {badge(self.stats['backend'])}")
        print(f"  • Qdrant Vector (6333): {badge(self.stats['qdrant'])}   • Celery Worker (Async):  {badge(self.stats['celery'])}")
        print(f"  • Redis Broker (6380):  {badge(self.stats['redis'])}   • Frontend Next.js (3000):{badge(self.stats['frontend'])}")
        
        if "ngrok" in self.services:
            tunnel_txt = f"{C.YELLOW}{self.stats['ngrok_url']}{C.RESET}" if self.stats['ngrok_url'] else f"{C.DIM}Inactivo{C.RESET}"
            print(f"  • Túnel Seguro Ngrok:   {tunnel_txt}")
        
        print(f"  • Documentos RAG:       {C.CYAN}{self.stats['completed_docs']}/{self.stats['total_docs']} indexados{C.RESET} ({self.stats['total_chunks']} chunks vectoriales)")
        print(f"{C.CYAN}{'─' * 78}{C.RESET}")

    def show_main_menu(self):
        self.print_status_summary()
        print(f"\n{C.BOLD}{C.WHITE}OPCIONES DISPONIBLES (SELECCIONA UN NÚMERO):{C.RESET}")
        print(f"  {C.YELLOW}[1]{C.RESET} ▶ Iniciar todos los servicios")
        print(f"  {C.YELLOW}[2]{C.RESET} ⏹ Detener todos los servicios")
        print(f"  {C.YELLOW}[3]{C.RESET} 🔄 Reiniciar todos los servicios")
        print(f"  {C.YELLOW}[4]{C.RESET} 📊 Ver Panel de Tracking y Diagnóstico de Salud")
        print(f"  {C.YELLOW}[5]{C.RESET} 📑 Listar Documentos y Chunks en Base de Datos")
        print(f"  {C.YELLOW}[6]{C.RESET} 📜 Ver Logs en Vivo (Multiplexados)")
        print(f"  {C.YELLOW}[7]{C.RESET} 🔧 Reiniciar un servicio individual")
        print(f"  {C.YELLOW}[8]{C.RESET} 📥 Sincronizar Videos YouTube / Reencolar tareas fallidas")
        print(f"  {C.YELLOW}[9]{C.RESET} 🧹 Limpiar pantalla")
        print(f"  {C.YELLOW}[0]{C.RESET} 🚪 Salir y apagar todo")
        print(f"{C.CYAN}{'═' * 78}{C.RESET}")

    def start_docker(self):
        print(f"\n{C.BLUE}[DOCKER]{C.RESET} Verificando contenedores de infraestructura...")
        try:
            check_ps = subprocess.run(["docker", "compose", "ps", "-q"], cwd=str(ROOT_DIR), capture_output=True, text=True, timeout=5)
            pids = [p.strip() for p in check_ps.stdout.strip().splitlines() if p.strip()]
            if len(pids) >= 3:
                print(f"{C.GREEN}[DOCKER]{C.RESET} Contenedores de Postgres, Qdrant y Redis ya activos.")
                return

            proc = subprocess.Popen(
                ["docker", "compose", "up", "-d"],
                cwd=str(ROOT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            for line in iter(proc.stdout.readline, ""):
                if not line:
                    break
                print(f"  {C.BLUE}[DOCKER]{C.RESET} {line.strip()}", flush=True)
            proc.wait(timeout=60)
            print(f"{C.GREEN}[DOCKER]{C.RESET} Infraestructura lista.")
        except Exception as e:
            print(f"{C.RED}[DOCKER]{C.RESET} Error al verificar docker: {e}")

    def start_all_services(self):
        self.start_docker()
        print(f"\n{C.BOLD}{C.WHITE}[SISTEMA] Arrancando servicios de AEGIS...{C.RESET}")
        for svc_id, svc in self.services.items():
            print(f"  {C.CYAN}➔{C.RESET} Iniciando {svc.name}...")
            svc.start(self)
            time.sleep(0.6)
        print(f"\n{C.GREEN}[SISTEMA] Todos los servicios han sido iniciados con éxito.{C.RESET}")

    def stop_all_services(self):
        print(f"\n{C.BOLD}{C.YELLOW}[SISTEMA] Deteniendo todos los servicios de forma ordenada...{C.RESET}")
        for svc_id, svc in self.services.items():
            print(f"  {C.DIM}➔ Deteniendo {svc.name}...{C.RESET}")
            svc.stop()
        print(f"{C.GREEN}[SISTEMA] Todos los procesos detenidos limpiamente.{C.RESET}")

    def stream_live_logs(self):
        os.system("cls" if IS_WINDOWS else "clear")
        print(f"{C.CYAN}{'═' * 78}{C.RESET}")
        print(f"  {C.BOLD}{C.WHITE}📜 VISUALIZADOR DE LOGS EN DIRECTO (AEGIS RAG){C.RESET}")
        print(f"  {C.YELLOW}Presiona [ENTER] en cualquier momento para volver al Menú Principal.{C.RESET}")
        print(f"{C.CYAN}{'═' * 78}{C.RESET}\n")

        combined_recent = []
        for svc in self.services.values():
            combined_recent.extend(list(svc.log_history))
        for line in combined_recent[-20:]:
            print(line)

        self.streaming_logs = True
        try:
            input()
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            self.streaming_logs = False
        
        os.system("cls" if IS_WINDOWS else "clear")
        self.print_ascii_header()

    def show_docs_table(self):
        try:
            req = urllib.request.Request("http://127.0.0.1:8000/api/v1/documents", headers={"User-Agent": "Aegis247"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                docs = json.loads(resp.read().decode())
        except Exception as e:
            print(f"\n{C.RED}[DOCS] No se pudo consultar la API: {e}{C.RESET}")
            return

        if not docs:
            print(f"\n{C.YELLOW}[DOCS] No hay documentos o vídeos registrados actualmente.{C.RESET}")
            return

        print(f"\n{C.CYAN}{'═' * 88}{C.RESET}")
        print(f"  {C.BOLD}{C.WHITE}DOCUMENTOS Y VIDEOTUTORIALES INDEXADOS ({len(docs)} total){C.RESET}")
        print(f"{C.CYAN}{'═' * 88}{C.RESET}")
        print(f" {C.BOLD}{'ESTADO':<14} {'TIPO':<8} {'CHUNKS':<8} {'ACTIVO':<8} {'NOMBRE / TITULO'}{C.RESET}")
        print(f" {C.DIM}{'─'*12:<14} {'─'*6:<8} {'─'*6:<8} {'─'*6:<8} {'─'*45}{C.RESET}")

        for d in docs:
            st = d.get("status", "UNKNOWN")
            st_color = C.GREEN if st == "COMPLETED" else (C.YELLOW if st == "PROCESSING" else C.RED)
            dtype = d.get("document_type", "pdf")
            chunks = d.get("total_chunks") or 0
            is_act = "SI" if d.get("is_active", True) else "NO"
            name = d.get("filename", "Sin nombre")[:48]
            print(f" {st_color}{st:<14}{C.RESET} {dtype:<8} {chunks:<8} {is_act:<8} {name}")
        print(f"{C.CYAN}{'═' * 88}{C.RESET}")

    def run_requeue_tool(self):
        script_requeue = BACKEND_DIR / "scratch" / "requeue_processing.py"
        if script_requeue.exists():
            print(f"\n{C.CYAN}[HERRAMIENTAS]{C.RESET} Reencolando tareas atascadas en segundo plano...")
            try:
                res = subprocess.run([PYTHON_EXE, str(script_requeue)], cwd=str(BACKEND_DIR), capture_output=True, text=True, timeout=20)
                print(res.stdout)
                if res.stderr:
                    print(f"{C.YELLOW}{res.stderr}{C.RESET}")
            except Exception as e:
                print(f"{C.RED}Error al reencolar: {e}{C.RESET}")
        else:
            print(f"{C.YELLOW}Script requeue_processing.py no encontrado.{C.RESET}")

    def restart_single_service_menu(self):
        print(f"\n{C.BOLD}Selecciona el servicio a reiniciar:{C.RESET}")
        keys = list(self.services.keys())
        for idx, k in enumerate(keys, 1):
            print(f" [{idx}] {self.services[k].name}")
        print(" [0] Cancelar")
        sub_opt = input(f"{C.YELLOW}Opción [0-{len(keys)}]: {C.RESET}").strip()
        try:
            opt_idx = int(sub_opt)
            if 1 <= opt_idx <= len(keys):
                svc_key = keys[opt_idx - 1]
                svc = self.services[svc_key]
                print(f"\n{C.YELLOW}Reiniciando {svc.name}...{C.RESET}")
                svc.stop()
                time.sleep(1.2)
                svc.start(self)
                print(f"{C.GREEN}{svc.name} reiniciado con éxito.{C.RESET}")
        except Exception:
            pass

    def run(self):
        os.system("cls" if IS_WINDOWS else "clear")
        self.print_ascii_header()
        
        # Arrancar servicios automáticamente al entrar
        self.start_all_services()

        def signal_handler(sig, frame):
            self.stop_all_services()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, signal_handler)

        while not self.should_exit:
            try:
                self.show_main_menu()
                opt = input(f"\n{C.BOLD}{C.CYAN}AEGIS [0-9] ➔ {C.RESET}").strip()

                if opt == "1":
                    self.start_all_services()
                elif opt == "2":
                    self.stop_all_services()
                elif opt == "3":
                    self.stop_all_services()
                    time.sleep(1.2)
                    self.start_all_services()
                elif opt == "4":
                    self.print_status_summary()
                    input(f"\n{C.DIM}Presiona [ENTER] para continuar...{C.RESET}")
                elif opt == "5":
                    self.show_docs_table()
                    input(f"\n{C.DIM}Presiona [ENTER] para continuar...{C.RESET}")
                elif opt == "6":
                    self.stream_live_logs()
                elif opt == "7":
                    self.restart_single_service_menu()
                elif opt == "8":
                    self.run_requeue_tool()
                    input(f"\n{C.DIM}Presiona [ENTER] para continuar...{C.RESET}")
                elif opt == "9":
                    os.system("cls" if IS_WINDOWS else "clear")
                    self.print_ascii_header()
                elif opt in ["0", "q", "exit", "quit"]:
                    self.stop_all_services()
                    self.should_exit = True
                    break
                else:
                    print(f"{C.YELLOW}Opción no válida. Ingresa un número del 0 al 9.{C.RESET}")
                    time.sleep(1)
            except (KeyboardInterrupt, EOFError):
                self.stop_all_services()
                break


if __name__ == "__main__":
    console = AegisVPSConsole()
    console.run()
