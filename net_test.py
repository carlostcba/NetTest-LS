import sys
import os
import subprocess
import re
import time
import socket
import threading
import binascii
import tempfile
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout, 
                             QHBoxLayout, QWidget, QTextEdit, QLabel, QFrame, 
                             QLineEdit, QComboBox, QMessageBox, QListView, QSizePolicy)
from PyQt6.QtGui import QPixmap, QFont, QTextCursor, QColor, QIcon
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QMetaObject, Q_ARG, pyqtSlot

try:
    import requests
except ImportError:
    print("Falta instalar requests: pip install requests")
    sys.exit(1)

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# === BASE DE DATOS DE VLANs ===
VLANS = {
    "1": {"nombre": "Default", "red": "192.168.1"},
    "2": {"nombre": "VOIP", "red": "192.168.2"},
    "10": {"nombre": "SOPORTE IT", "red": "10.0.10"},
    "11": {"nombre": "INFRA IT", "red": "10.0.0"},
    "30": {"nombre": "ADMINISTRACION", "red": "192.168.30"},
    "40": {"nombre": "SEGURIDAD", "red": "192.168.40"},
    "69": {"nombre": "EVENTOS", "red": "192.168.69"},
    "120": {"nombre": "BIBLIOTECA", "red": "192.168.120"},
    "150": {"nombre": "LAB ELEC 1", "red": "192.168.150"},
    "151": {"nombre": "LAB TANGO", "red": "192.168.151"},
    "152": {"nombre": "LAB COMP 1", "red": "192.168.152"},
    "153": {"nombre": "LAB COMP 2", "red": "192.168.153"},
    "154": {"nombre": "LAB ESTUDIO TV", "red": "192.168.154"},
    "155": {"nombre": "LAB ELEC 2", "red": "192.168.155"},
    "156": {"nombre": "LAB DAC", "red": "192.168.156"},
    "157": {"nombre": "LAB ENERGIA 3", "red": "192.168.157"},
    "159": {"nombre": "CREATIVO DIG", "red": "192.168.169"},
    "160": {"nombre": "LA SALLE WIFI", "red": "192.168.160"},
    "170": {"nombre": "LA SALLE EQUIPOS", "red": "192.168.170"},
    "180": {"nombre": "LA SALLE ESTUDIANTES", "red": "192.168.180"},
    "199": {"nombre": "KIOSCOS", "red": "192.168.199"},
    "200": {"nombre": "NO DOCENTE", "red": "192.168.200"},
    "210": {"nombre": "NVL INICIAL", "red": "192.168.210"},
    "220": {"nombre": "NVL PRIMARIO", "red": "192.168.220"},
    "230": {"nombre": "NVL SECUNDARIO", "red": "192.168.230"},
}

class NetworkWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(dict)
    solicitar_ip_manual_signal = pyqtSignal()

    def __init__(self, iface_name, dominio_objetivo):
        super().__init__()
        self.iface_name = iface_name
        self.dominio_objetivo = dominio_objetivo.lower().replace("https://", "").replace("http://", "")
        self.evento_espera = threading.Event()
        self.ip_manual_config = None
        self.resultados = {"capa1": "N/A", "capa2": "N/A", "capa3": "N/A", "dns": "N/A", "internet": "N/A"}
        self._is_running = True
        self.current_process = None

    def log(self, mensaje):
        self.log_signal.emit(mensaje)

    def stop(self):
        """Detiene la ejecución al instante matando procesos residuales"""
        self._is_running = False
        self.evento_espera.set()
        if self.current_process:
            try:
                self.current_process.kill()
            except Exception:
                pass

    def ejecutar_comando(self, cmd, timeout=None):
        if not self._is_running: return ""
        try:
            self.current_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='cp850', creationflags=CREATE_NO_WINDOW)
            try:
                salida, _ = self.current_process.communicate(timeout=timeout)
                return salida
            except subprocess.TimeoutExpired:
                self.current_process.kill()
                salida, _ = self.current_process.communicate()
                return salida + "\n<span style='color: orange;'>[!] El comando excedió el tiempo de espera.</span>"
        except Exception as e:
            return str(e)

    def run(self):
        try:
            self.ejecutar_diagnostico()
        except Exception as e:
            if self._is_running:
                self.log(f"<span style='color: red;'><b>Error fatal:</b> {str(e)}</span>")
        finally:
            if self._is_running:
                self.generar_reporte_final()
            self.finished_signal.emit(self.resultados)

    def ejecutar_diagnostico(self):
        if not self._is_running: return
        # === [1] PRUEBAS DE CAPA 1 (FÍSICA) ===
        self.log("<b>=== [1] PRUEBAS DE CAPA 1 (FÍSICA) ===</b>")
        ps_cmd = f"Get-NetAdapter -Name '{self.iface_name}' | Select-Object Status, MediaConnectionState | ConvertTo-Csv -NoTypeInformation"
        salida_c1 = self.ejecutar_comando(['powershell', '-command', ps_cmd])
        if not self._is_running: return

        if "Up" not in salida_c1 and "Connected" not in salida_c1:
            self.log("<span style='color: red;'>[-] ERROR CAPA 1: No hay enlace físico.</span>")
            self.log("<span style='color: gray;'>Posibles causas:\n- Cable desconectado\n- Puerto de switch apagado\n- Tarjeta deshabilitada</span>")
            self.resultados["capa1"] = "ERROR ENLACE"
            return 
        self.log("<span style='color: green;'>[+] Enlace físico detectado (UP).</span>")
        self.resultados["capa1"] = "OK"

        if not self._is_running: return
        # === [2] PRUEBAS DE CAPA 2 (ENLACE DE DATOS) ===
        self.log("<br><b>=== [2] PRUEBAS DE CAPA 2 (ENLACE DE DATOS) ===</b>")
        config = self.obtener_ip_actual()
        if not self._is_running: return
        
        if not config['ip'] or config['ip'].startswith('169.254.') or config['ip'] == '0.0.0.0':
            self.log("<span style='color: orange;'>[!] IP no válida detectada (APIPA/Nula). Iniciando proceso DORA (Release/Renew)...</span>")
            
            self.ejecutar_comando(['ipconfig', '/release', self.iface_name])
            if not self._is_running: return
            time.sleep(1)
            self.log("Renovando IP (Tiempo máximo: 15 seg)...")
            self.ejecutar_comando(['ipconfig', '/renew', self.iface_name], timeout=15)
            if not self._is_running: return
            
            config = self.obtener_ip_actual()
            
            if not config['ip'] or config['ip'].startswith('169.254.'):
                self.log("<span style='color: red;'>[-] ERROR DHCP: El servidor no respondió o el Pool está agotado.</span>")
                self.resultados["capa2"] = "ERROR DHCP"
                
                self.log("<span style='color: #3b82f6;'>[i] Pausando diagnóstico. Esperando asignación manual de IP...</span>")
                self.solicitar_ip_manual_signal.emit()
                
                # Hilo se congela aquí hasta que el usuario aplique IP manual o presione DETENER
                self.evento_espera.wait()
                if not self._is_running: return
                
                if not self.ip_manual_config:
                    self.log("<span style='color: red;'>[-] Asignación manual cancelada. Deteniendo diagnóstico.</span>")
                    return
                
                config = self.aplicar_ip_manual(self.ip_manual_config)
                if not config or not self._is_running: return
            else:
                self.log("<span style='color: green;'>[+] Renovación DHCP exitosa.</span>")
                self.resultados["capa2"] = "OK"
        else:
            self.log(f"<span style='color: green;'>[+] Configuración IP válida detectada: {config['ip']}</span>")
            self.log(f"<span style='color: green;'>[+] Puerta de Enlace detectada: {config['gateway']}</span>")
            self.resultados["capa2"] = "OK"

        gateway = config.get('gateway')
        if not gateway:
            self.log("<span style='color: red;'>[-] ERROR: No se detectó Puerta de Enlace. Imposible testear Capa 3.</span>")
            return

        if not self._is_running: return
        # === [3] PRUEBAS DE CAPA 3 (RED) ===
        self.log("<br><b>=== [3] PRUEBAS DE CAPA 3 (RED) ===</b>")
        
        self.log(f"Consultando MAC del Gateway ({gateway}) en tabla ARP...")
        salida_arp = self.ejecutar_comando(['arp', '-a'])
        if not self._is_running: return
        if gateway not in salida_arp:
            self.log("<span style='color: orange;'>[!] ALERTA ARP: La IP del Gateway no está en la tabla ARP. Posible VLAN incorrecta o puerto aislado.</span>")
        else:
            self.log("<span style='color: green;'>[+] Gateway encontrado en tabla ARP.</span>")

        self.log(f"Enviando 10 paquetes ICMP al Gateway ({gateway})...")
        salida_gw = self.ejecutar_comando(['ping', '-n', '10', '-w', '1000', gateway])
        if not self._is_running: return
        perdida_gw = self.analizar_ping(salida_gw)
        
        if perdida_gw > 5:
            self.log(f"<span style='color: red;'>[-] PROBLEMA DE RED LOCAL: Pérdida de paquetes hacia el gateway ({perdida_gw}%).</span>")
            self.resultados["capa3"] = "ERROR LOCAL"
            return
        self.log("<span style='color: green;'>[+] Ping a Gateway: OK.</span>")

        self.log("Enviando paquetes ICMP a Internet (8.8.8.8)...")
        salida_int = self.ejecutar_comando(['ping', '-n', '10', '-w', '1000', '8.8.8.8'])
        if not self._is_running: return
        perdida_int = self.analizar_ping(salida_int)
        
        if perdida_int > 5:
            self.log("<span style='color: red;'>[-] Gateway responde pero NO hay salida a Internet (Posible ruteo/firewall).</span>")
            self.resultados["capa3"] = "ERROR RUTEO"
            return
            
        self.log("Verificando fragmentación (MTU 1472)...")
        salida_mtu = self.ejecutar_comando(['ping', '8.8.8.8', '-f', '-l', '1472', '-n', '1'])
        if not self._is_running: return
        if "fragmentado" in salida_mtu or "fragmented" in salida_mtu:
             self.log("<span style='color: orange;'>[!] ALERTA MTU: Los paquetes requieren fragmentación.</span>")
        
        self.log("<span style='color: green;'>[+] Salida a Internet y MTU: OK.</span>")
        self.resultados["capa3"] = "OK"

        if not self._is_running: return
        # === [4] PRUEBAS DE DNS Y APLICACIÓN ===
        self.log("<br><b>=== [4] PRUEBAS DE DNS Y APLICACIÓN ===</b>")
        
        dominios_a_testear = list(set(['drive.google.com', self.dominio_objetivo]))
        dns_ok = True
        
        for dom in dominios_a_testear:
            if not dom: continue
            try:
                ip_dom = socket.gethostbyname(dom)
                self.log(f"[+] DNS resolvió {dom} -> {ip_dom}")
            except Exception:
                self.log(f"<span style='color: red;'>[-] ERROR DNS: No se pudo resolver {dom}</span>")
                dns_ok = False
        if not self._is_running: return
        self.resultados["dns"] = "OK" if dns_ok else "ERROR"

        try:
            self.log(f"Simulando navegación web HTTP(S) hacia {self.dominio_objetivo}...")
            headers_falsos = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
            url_test = f"https://{self.dominio_objetivo}"
            
            t_start = time.time()
            r = requests.get(url_test, headers=headers_falsos, timeout=5)
            t_end = time.time()
            if not self._is_running: return
            
            if r.status_code == 200:
                self.log(f"<span style='color: green;'>[+] HTTP 200 OK en {self.dominio_objetivo} ({(t_end - t_start)*1000:.0f}ms).</span>")
                self.resultados["internet"] = "OK"
            else:
                self.log(f"<span style='color: orange;'>[!] El dominio devolvió código {r.status_code}. Verificando portal Microsoft...</span>")
                r_ms = requests.get('http://www.msftconnecttest.com/connecttest.txt', timeout=5)
                if r_ms.status_code == 200 and "Microsoft Connect Test" in r_ms.text:
                    self.log("<span style='color: green;'>[+] Conectividad web oficial de Windows: OK.</span>")
                    self.resultados["internet"] = "OK"
                else:
                    self.log(f"<span style='color: red;'>[-] Código HTTP inesperado: Fallo general de navegación.</span>")
                    self.resultados["internet"] = "ERROR HTTP"
                    
        except Exception as e:
            if self._is_running:
                self.log(f"<span style='color: red;'>[-] ERROR DE NAVEGACIÓN hacia {self.dominio_objetivo}: {str(e)}</span>")
                self.resultados["internet"] = "ERROR"

    def obtener_ip_actual(self):
        info = {"ip": None, "gateway": None}
        ps_ip = f"(Get-NetIPAddress -InterfaceAlias '{self.iface_name}' -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress"
        salida_ip = self.ejecutar_comando(['powershell', '-command', ps_ip]).strip()
        if salida_ip:
            ip_limpia = salida_ip.split('\n')[0].strip()
            if re.match(r'^\d+\.\d+\.\d+\.\d+$', ip_limpia): info['ip'] = ip_limpia

        ps_gw = f"(Get-NetRoute -InterfaceAlias '{self.iface_name}' -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1).NextHop"
        salida_gw = self.ejecutar_comando(['powershell', '-command', ps_gw]).strip()
        if salida_gw:
            gw_limpio = salida_gw.split('\n')[0].strip()
            if re.match(r'^\d+\.\d+\.\d+\.\d+$', gw_limpio): info['gateway'] = gw_limpio
        return info

    def aplicar_ip_manual(self, conf):
        ip = conf['ip']
        gw = conf['gateway']
        
        self.log(f"Verificando conflicto para IP {ip}...")
        salida_ping = self.ejecutar_comando(['ping', '-n', '1', '-w', '1000', ip])
        if not self._is_running: return None
        if "recibidos = 1" in salida_ping.lower() or "received = 1" in salida_ping.lower():
             self.log(f"<span style='color: red;'>[-] CONFLICTO: La IP {ip} ya está en uso. Operación abortada.</span>")
             self.resultados["capa2"] = "CONFLICTO IP"
             return None

        self.log(f"Aplicando IP estática: {ip} ...")
        self.ejecutar_comando(f'netsh interface ip set address name="{self.iface_name}" static {ip} 255.255.255.0 {gw}')
        self.ejecutar_comando(f'netsh interface ip set dns name="{self.iface_name}" static 8.8.8.8')
        self.ejecutar_comando(f'netsh interface ip add dns name="{self.iface_name}" 1.1.1.1 index=2')
        if not self._is_running: return None
        
        self.log("Esperando asimilación del SO...")
        time.sleep(3)
        if not self._is_running: return None
        
        nueva_conf = self.obtener_ip_actual()
        self.log(f"<span style='color: green;'>[+] Configuración manual aplicada.</span>")
        self.resultados["capa2"] = "OK (MANUAL)"
        return nueva_conf

    def analizar_ping(self, salida):
        match = re.search(r'\((\d+)% [pP]', salida)
        if match: return int(match.group(1))
        return 100

    def generar_reporte_final(self):
        self.log("<br><b>========== RESULTADO DIAGNÓSTICO ==========</b>")
        for capa, res in self.resultados.items():
            color = "green" if "OK" in res else ("gray" if res == "N/A" else "red")
            self.log(f"<b>{capa.upper()}:</b> <span style='color: {color};'>{res}</span>")
            
        self.log("<br><b>CONCLUSIÓN:</b>")
        if self.resultados["capa1"] != "OK": self.log("Fallo físico detectado. Revise el cableado o puerto de red.")
        elif self.resultados["capa2"] == "ERROR DHCP": self.log("El servidor DHCP no asigna IP. Posible pool agotado.")
        elif self.resultados["capa2"] == "OK (MANUAL)" and self.resultados["internet"] == "OK": self.log("Servidor DHCP caído. Al fijar IP manual la red funciona perfectamente.")
        elif self.resultados["capa3"] == "ERROR LOCAL": self.log("Problema en red local. Alta latencia o VLAN incorrecta hacia el Gateway.")
        elif self.resultados["internet"] == "OK": self.log("Conectividad completamente normal.")
        else: self.log("Existen bloqueos de ruteo, DNS o Firewall hacia el exterior.")


class TroubleshooterLaSalle(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("La Salle - Centro de Diagnóstico Automático")
        self.is_testing = False
        
        icon_path = os.path.join(sys._MEIPASS, "icon.ico") if getattr(sys, 'frozen', False) else "icon.ico"
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.resize(1000, 600)
        self.setMinimumSize(900, 600)
        self.setup_styles()
        self.create_widgets()
        self.cargar_interfaces_completas()
        
        # Conectar cambio de interfaz para mostrar/ocultar paneles
        self.combo_iface.currentIndexChanged.connect(self.actualizar_visibilidad_paneles)
        self.actualizar_visibilidad_paneles()

    def setup_styles(self):
        self.setStyleSheet("""
        QMainWindow { background-color: #f8fafc; }
        QFrame#Header { background-color: #1e3a8a; }
        QLabel#HeaderName { color: white; font-family: 'Segoe UI'; font-size: 18px; font-weight: bold; letter-spacing: 0.5px; }
        QFrame#Card { background-color: white; border: 2px solid #ACC8E5; border-radius: 10px; }
        QLabel#CardTitle { color: #1e293b; font-family: 'Segoe UI'; font-size: 14px; font-weight: 600; margin-bottom: 5px;}
        
        QComboBox, QLineEdit { border: 2px solid #e2e8f0; border-radius: 6px; padding: 8px 40px 8px 12px; font-family: 'Segoe UI'; font-size: 13px; color: #334155; background-color: white; min-height: 22px;}
        QLineEdit { padding: 8px 12px; }
        QComboBox:hover, QLineEdit:hover { border: 2px solid #cbd5e1; }
        QComboBox:focus, QLineEdit:focus { border: 2px solid #3b82f6; background-color: #ffffff;}
        
        QComboBox::drop-down { subcontrol-origin: border; subcontrol-position: right; width: 36px; background-color: #1e3a8a; border-top-right-radius: 4px; border-bottom-right-radius: 4px; }
        QComboBox::drop-down:hover { background-color: #1d4ed8; }
        QComboBox::down-arrow { image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>"); width: 16px; height: 16px;}
        QComboBox QListView { border: 1px solid #cbd5e1; border-radius: 6px; background-color: white; selection-background-color: #eff6ff; selection-color: #1e3a8a; outline: none; }
        QComboBox QListView::item { padding: 10px; min-height: 20px; }
        
        QPushButton#BtnPrimary { background-color: #1e3a8a; color: white; border-radius: 6px; padding: 12px; font-weight: bold; font-family: 'Segoe UI'; font-size: 14px; }
        QPushButton#BtnPrimary:hover { background-color: #1d4ed8; }
        QPushButton#BtnPrimary:disabled { background-color: #94a3b8; color: #f1f5f9; }
        
        QPushButton#BtnSecondary { background-color: #f1f5f9; color: #1e293b; border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px 12px; font-weight: bold; font-family: 'Segoe UI'; font-size: 13px; }
        QPushButton#BtnSecondary:hover { background-color: #e2e8f0; }
        
        QFrame#ManualPanel { background-color: #fffbeb; border: 2px solid #fcd34d; border-radius: 8px; padding: 5px; }
        QFrame#WifiPanel { background-color: #f0fdf4; border: 1px solid #86efac; border-radius: 8px; padding: 4px 8px; }
        QLabel#AlertaManual { color: #b45309; font-size: 13px; font-family: 'Segoe UI'; }
        QLabel#WifiTitle { color: #166534; font-size: 12px; font-weight: bold; font-family: 'Segoe UI'; }
        QTextEdit#Console { background-color: #ffffff; border: none; font-family: 'Consolas', monospace; font-size: 13px; padding: 15px; color: #1e293b; }
        """)

    def create_widgets(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 20)

        header = QFrame(objectName="Header")
        header.setFixedHeight(60)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(40, 0, 40, 0)
        
        logo_path = os.path.join(sys._MEIPASS, "logo_lasalle.png") if getattr(sys, 'frozen', False) else "logo_lasalle.png"
        if os.path.exists(logo_path):
            logo_lbl = QLabel()
            pixmap = QPixmap(logo_path)
            logo_lbl.setPixmap(pixmap.scaledToHeight(45, Qt.TransformationMode.SmoothTransformation))
            h_layout.addWidget(logo_lbl)
            h_layout.addSpacing(15)
            
        lbl_title = QLabel("Centro de Diagnóstico Automático", objectName="HeaderName")
        h_layout.addWidget(lbl_title)
        h_layout.addStretch()
        main_layout.addWidget(header)

        content = QVBoxLayout()
        content.setContentsMargins(40, 10, 40, 0)
        content.setSpacing(10)

        card_ctrl = QFrame(objectName="Card")
        ctrl_layout = QVBoxLayout(card_ctrl)
        ctrl_layout.setContentsMargins(30, 15, 30, 15)
        ctrl_layout.setSpacing(10)
        
        # Selectores en una sola fila
        row_selectors = QHBoxLayout()
        
        v_iface = QVBoxLayout()
        v_iface.addWidget(QLabel("Selección de Interfaz de Red", objectName="CardTitle"))
        self.combo_iface = QComboBox()
        self.combo_iface.setView(QListView()) 
        v_iface.addWidget(self.combo_iface)
        row_selectors.addLayout(v_iface, stretch=2)
        
        v_url = QVBoxLayout()
        v_url.addWidget(QLabel("Dominio web a evaluar", objectName="CardTitle"))
        self.combo_url = QComboBox()
        self.combo_url.setEditable(True)
        self.combo_url.setView(QListView())
        self.combo_url.addItems(["lasalleflorida.edu.ar", "academia.creativos-digitales.com", "mercadolibre.com.ar", "google.com"])
        v_url.addWidget(self.combo_url)
        row_selectors.addLayout(v_url, stretch=1)
        
        ctrl_layout.addLayout(row_selectors)

        self.btn_iniciar = QPushButton("Iniciar Diagnóstico Completo", objectName="BtnPrimary")
        self.btn_iniciar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_iniciar.clicked.connect(self.toggle_diagnostico)
        ctrl_layout.addWidget(self.btn_iniciar)
        
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #e2e8f0; margin-top: 5px; margin-bottom: 5px;")
        ctrl_layout.addWidget(line)
        
        lbl_quick = QLabel("Gestión Rápida de Interfaz IP (Sin testear):")
        lbl_quick.setStyleSheet("color: #64748b; font-size: 12px; font-weight: bold;")
        ctrl_layout.addWidget(lbl_quick)
        
        h_quick_btns = QHBoxLayout()
        self.btn_quick_dhcp = QPushButton("🌐 Forzar IP Automática (DHCP)", objectName="BtnSecondary")
        self.btn_quick_dhcp.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_quick_dhcp.clicked.connect(self.quick_set_dhcp)
        
        self.btn_quick_static = QPushButton("⚙️ Fijar IP Manual", objectName="BtnSecondary")
        self.btn_quick_static.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_quick_static.clicked.connect(self.toggle_panel_manual_standalone)
        
        h_quick_btns.addWidget(self.btn_quick_dhcp)
        h_quick_btns.addWidget(self.btn_quick_static)
        ctrl_layout.addLayout(h_quick_btns)

        # Panel IP Manual
        self.panel_manual = QFrame(objectName="ManualPanel")
        self.panel_manual.hide()
        pm_layout = QVBoxLayout(self.panel_manual)
        
        self.lbl_alerta_manual = QLabel("<b>Configure la IP estática:</b>", objectName="AlertaManual")
        pm_layout.addWidget(self.lbl_alerta_manual)
        
        h_manual = QHBoxLayout()
        self.combo_vlan = QComboBox()
        self.combo_vlan.setView(QListView())
        for v_id, datos in VLANS.items():
            self.combo_vlan.addItem(f"VLAN {v_id} - {datos['nombre']} ({datos['red']}.X)", v_id)
        self.combo_vlan.currentIndexChanged.connect(self.actualizar_preview_ip)
        h_manual.addWidget(self.combo_vlan, stretch=2)
        
        self.txt_octeto = QLineEdit()
        self.txt_octeto.setPlaceholderText("Último Octeto (ej. 50)")
        self.txt_octeto.textChanged.connect(self.actualizar_preview_ip)
        h_manual.addWidget(self.txt_octeto, stretch=1)
        pm_layout.addLayout(h_manual)
        
        self.lbl_preview = QLabel("IP a asignar: -")
        self.lbl_preview.setStyleSheet("color: #475569; font-size: 13px;")
        pm_layout.addWidget(self.lbl_preview)
        
        self.btn_aplicar = QPushButton("Aplicar Configuración IP", objectName="BtnPrimary")
        self.btn_aplicar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_aplicar.clicked.connect(self.aplicar_ip)
        pm_layout.addWidget(self.btn_aplicar)
        ctrl_layout.addWidget(self.panel_manual)

        # Panel Wi-Fi Compacto
        self.panel_wifi = QFrame(objectName="WifiPanel")
        self.panel_wifi.hide()
        pw_layout = QVBoxLayout(self.panel_wifi)
        pw_layout.setSpacing(4)
        pw_layout.setContentsMargins(8, 6, 8, 6)
        
        h_wifi_top = QHBoxLayout()
        h_wifi_top.addWidget(QLabel("<b>Gestión Wi-Fi:</b>", objectName="WifiTitle"))
        h_wifi_top.addStretch()
        
        self.btn_refrescar_wifi = QPushButton("🔄 Scan", objectName="BtnSecondary")
        self.btn_refrescar_wifi.setFixedWidth(80)
        self.btn_refrescar_wifi.setFixedHeight(28)
        self.btn_refrescar_wifi.clicked.connect(self.escanear_wifi)
        h_wifi_top.addWidget(self.btn_refrescar_wifi)
        
        self.btn_olvidar_wifi = QPushButton("🗑 Olvidar", objectName="BtnSecondary")
        self.btn_olvidar_wifi.setFixedWidth(80)
        self.btn_olvidar_wifi.setFixedHeight(28)
        self.btn_olvidar_wifi.setStyleSheet("color: #991b1b; border-color: #fecaca;")
        self.btn_olvidar_wifi.clicked.connect(self.olvidar_wifi)
        h_wifi_top.addWidget(self.btn_olvidar_wifi)
        pw_layout.addLayout(h_wifi_top)
        
        h_wifi_main = QHBoxLayout()
        self.combo_ssids = QComboBox()
        self.combo_ssids.setView(QListView())
        self.combo_ssids.setPlaceholderText("Seleccionar Red...")
        h_wifi_main.addWidget(self.combo_ssids, stretch=3)
        
        self.txt_wifi_pass = QLineEdit()
        self.txt_wifi_pass.setPlaceholderText("Contraseña")
        self.txt_wifi_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_wifi_pass.setFixedHeight(32)
        h_wifi_main.addWidget(self.txt_wifi_pass, stretch=3)
        
        self.btn_conectar_wifi = QPushButton("📡 Conectar", objectName="BtnPrimary")
        self.btn_conectar_wifi.setFixedHeight(32)
        self.btn_conectar_wifi.clicked.connect(self.conectar_wifi)
        h_wifi_main.addWidget(self.btn_conectar_wifi, stretch=2)
        pw_layout.addLayout(h_wifi_main)
        
        ctrl_layout.addWidget(self.panel_wifi)
        content.addWidget(card_ctrl)

        # Consola
        card_res = QFrame(objectName="Card")
        res_layout = QVBoxLayout(card_res)
        res_layout.setContentsMargins(0, 0, 0, 0)
        
        header_consola = QFrame()
        header_consola.setStyleSheet("background-color: #f1f5f9; border-bottom: 1px solid #e2e8f0; border-top-left-radius: 10px; border-top-right-radius: 10px;")
        hc_layout = QHBoxLayout(header_consola)
        hc_layout.setContentsMargins(20, 15, 20, 15)
        hc_layout.addWidget(QLabel("Log de Operaciones en Tiempo Real", objectName="CardTitle"))
        res_layout.addWidget(header_consola)

        self.consola = QTextEdit(objectName="Console")
        self.consola.setReadOnly(True)
        res_layout.addWidget(self.consola)
        content.addWidget(card_res, stretch=1)

        main_layout.addLayout(content)
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)
        self.actualizar_preview_ip()

    def cargar_interfaces_completas(self):
        try:
            cmd = "Get-NetAdapter | Select-Object Name, InterfaceDescription, MacAddress, Status, LinkSpeed, PhysicalMediaType | ConvertTo-Csv -NoTypeInformation"
            salida = subprocess.check_output(['powershell', '-command', cmd], text=True, creationflags=CREATE_NO_WINDOW)
            lineas = salida.strip().split('\n')[1:] 
            
            marcas_preferidas = ["realtek", "intel", "broadcom", "marvell", "qualcomm", "atheros"]
            lista_preferidos = []
            lista_otros = []

            for linea in lineas:
                datos = linea.replace('"', '').split(',')
                if len(datos) >= 6:
                    nombre, desc, mac, estado, vel, media = datos[0], datos[1], datos[2], datos[3], datos[4], datos[5]
                    is_wifi = "802.11" in media or "Native 802.11" in media or "Wi-Fi" in media
                    prefix = "📶" if is_wifi else "🌐"
                    item_data = {
                        "nombre": nombre, 
                        "is_wifi": is_wifi,
                        "display": f"{prefix} {desc}  |  MAC: {mac}  |  {estado} ({vel})"
                    }
                    
                    if any(marca in desc.lower() for marca in marcas_preferidas): lista_preferidos.append(item_data)
                    else: lista_otros.append(item_data)
            
            for item in lista_preferidos + lista_otros:
                self.combo_iface.addItem(item["display"], item)
        except Exception:
            self.combo_iface.addItem("Error al cargar interfaces")

    def actualizar_preview_ip(self):
        vlan_id = self.combo_vlan.currentData()
        octeto = self.txt_octeto.text().strip()
        if vlan_id and octeto.isdigit():
            red = VLANS[vlan_id]["red"]
            self.lbl_preview.setText(f"<b>Se configurará:</b> IP: {red}.{octeto}  |  Mascara: 255.255.255.0  |  GW: {red}.1  |  DNS: 8.8.8.8")
        else:
            self.lbl_preview.setText("Ingrese un número válido para el último octeto (1-254)")

    # --- NUEVAS FUNCIONES DE GESTION IP STANDALONE ---
    def quick_set_dhcp(self):
        data = self.combo_iface.currentData()
        if not data: return
        iface = data['nombre']
        self.consola.append(f"<br><span style='color: #1e3a8a;'><b>[⚙️] Forzando configuración DHCP Automática en '{iface}'...</b></span>")
        QApplication.processEvents()
        try:
            subprocess.run(f'netsh interface ip set address name="{iface}" dhcp', shell=True, creationflags=CREATE_NO_WINDOW)
            subprocess.run(f'netsh interface ip set dns name="{iface}" dhcp', shell=True, creationflags=CREATE_NO_WINDOW)
            self.consola.append("<span style='color: green;'>[+] Interfaz configurada en modo DHCP exitosamente.</span>")
        except Exception as e:
            self.consola.append(f"<span style='color: red;'>[-] Error al configurar DHCP: {e}</span>")

    def toggle_panel_manual_standalone(self):
        if self.panel_manual.isVisible() and self.lbl_alerta_manual.text() == "<b>Configuración Directa de IP Estática:</b>":
            self.panel_manual.hide()
        else:
            self.lbl_alerta_manual.setText("<b>Configuración Directa de IP Estática:</b>")
            self.lbl_alerta_manual.setStyleSheet("color: #1e3a8a;")
            self.btn_aplicar.setText("Aplicar IP Inmediatamente")
            self.panel_manual.show()

    def mostrar_panel_manual_rescate(self):
        self.lbl_alerta_manual.setText("<b>[!] Alerta: Falló DHCP. Seleccione VLAN para asignar IP manual y continuar test:</b>")
        self.lbl_alerta_manual.setStyleSheet("color: #b45309;")
        self.btn_aplicar.setText("Aplicar IP y Continuar Pruebas")
        self.panel_manual.show()

    def actualizar_visibilidad_paneles(self):
        data = self.combo_iface.currentData()
        if not data: return
        
        # Mostrar/Ocultar Panel WiFi
        if data.get("is_wifi"):
            self.panel_wifi.show()
            self.escanear_wifi()
        else:
            self.panel_wifi.hide()

    def escanear_wifi(self):
        self.combo_ssids.clear()
        self.combo_ssids.addItem("Escaneando...")
        self.combo_ssids.setEnabled(False)
        self.btn_refrescar_wifi.setEnabled(False)
        QApplication.processEvents()
        
        threading.Thread(target=self._worker_escanear_wifi, daemon=True).start()

    def _worker_escanear_wifi(self):
        try:
            # Forzar escaneo
            subprocess.run(['netsh', 'wlan', 'show', 'networks'], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
            # Obtener resultados
            salida = subprocess.check_output(['netsh', 'wlan', 'show', 'networks'], text=True, encoding='cp850', creationflags=CREATE_NO_WINDOW)
            ssids = []
            for linea in salida.split('\n'):
                if "SSID" in linea and ":" in linea:
                    ssid = linea.split(":", 1)[1].strip()
                    if ssid: ssids.append(ssid)
            
            # Quitar duplicados manteniendo orden
            ssids = list(dict.fromkeys(ssids))
            
            def update_ui():
                self.combo_ssids.clear()
                if ssids:
                    self.combo_ssids.addItems(ssids)
                else:
                    self.combo_ssids.addItem("No se encontraron redes")
                self.combo_ssids.setEnabled(True)
                self.btn_refrescar_wifi.setEnabled(True)
            
            # Usar threading.Timer o invocar en el hilo principal
            QMetaObject.invokeMethod(self, "actualizar_combo_ssids", Qt.ConnectionType.QueuedConnection, Q_ARG(list, ssids))
            
        except Exception as e:
            print(f"Error escaneando wifi: {e}")
            QMetaObject.invokeMethod(self, "actualizar_combo_ssids", Qt.ConnectionType.QueuedConnection, Q_ARG(list, []))

    @pyqtSlot(list)
    def actualizar_combo_ssids(self, ssids):
        self.combo_ssids.clear()
        if ssids:
            self.combo_ssids.addItems(ssids)
        else:
            self.combo_ssids.addItem("No se encontraron redes")
        self.combo_ssids.setEnabled(True)
        self.btn_refrescar_wifi.setEnabled(True)

    def conectar_wifi(self):
        ssid = self.combo_ssids.currentText()
        password = self.txt_wifi_pass.text()
        data = self.combo_iface.currentData()
        if not ssid or ssid == "Escaneando..." or ssid == "No se encontraron redes": return
        if not data: return
        
        iface = data['nombre']
        self.consola.append(f"<br><b>[📡] Intentando conectar a Wi-Fi: {ssid}...</b>")
        self.btn_conectar_wifi.setEnabled(False)
        QApplication.processEvents()

        def _task():
            success = False
            error_msg = ""
            try:
                # Crear perfil XML temporal
                guid = f"{{{ssid}}}" # No importa mucho el GUID real para netsh
                hex_ssid = binascii.hexlify(ssid.encode()).decode().upper()
                
                xml_content = f"""<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
    <name>{ssid}</name>
    <SSIDConfig>
        <SSID>
            <hex>{hex_ssid}</hex>
            <name>{ssid}</name>
        </SSID>
    </SSIDConfig>
    <connectionType>ESS</connectionType>
    <connectionMode>auto</connectionMode>
    <MSM>
        <security>
            <authEncryption>
                <authentication>WPA2PSK</authentication>
                <encryption>AES</encryption>
                <useOneX>false</useOneX>
            </authEncryption>
            <sharedKey>
                <keyType>passPhrase</keyType>
                <protected>false</protected>
                <keyMaterial>{password}</keyMaterial>
            </sharedKey>
        </security>
    </MSM>
</WLANProfile>"""
                
                with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
                    f.write(xml_content)
                    temp_path = f.name
                
                # Agregar perfil
                res_add = subprocess.run(['netsh', 'wlan', 'add', 'profile', f'filename={temp_path}', f'interface={iface}'], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                os.unlink(temp_path)
                
                # Conectar
                res_conn = subprocess.run(['netsh', 'wlan', 'connect', f'name={ssid}', f'interface={iface}'], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                
                time.sleep(2) # Esperar un poco a que negocie
                
                # Verificar estado
                res_state = subprocess.run(['netsh', 'wlan', 'show', 'interface', f'name={iface}'], capture_output=True, text=True, encoding='cp850', creationflags=CREATE_NO_WINDOW)
                if f"SSID" in res_state.stdout and ssid in res_state.stdout and "conectado" in res_state.stdout.lower() or "connected" in res_state.stdout.lower():
                    success = True
                else:
                    error_msg = res_conn.stderr or "Tiempo de espera agotado o contraseña incorrecta."
            except Exception as e:
                error_msg = str(e)
            
            def finish():
                if success:
                    self.consola.append(f"<span style='color: green;'>[+] Conectado exitosamente a {ssid}.</span>")
                    self.txt_wifi_pass.clear()
                else:
                    self.consola.append(f"<span style='color: red;'>[-] Falló la conexión: {error_msg}</span>")
                self.btn_conectar_wifi.setEnabled(True)
            
            QMetaObject.invokeMethod(self, "finish_conectar", Qt.ConnectionType.QueuedConnection, Q_ARG(bool, success), Q_ARG(str, error_msg))

        threading.Thread(target=_task, daemon=True).start()

    @pyqtSlot(bool, str)
    def finish_conectar(self, success, error_msg):
        ssid = self.combo_ssids.currentText()
        if success:
            self.consola.append(f"<span style='color: green;'>[+] Conectado exitosamente a {ssid}.</span>")
            self.txt_wifi_pass.clear()
        else:
            self.consola.append(f"<span style='color: red;'>[-] Falló la conexión: {error_msg}</span>")
        self.btn_conectar_wifi.setEnabled(True)

    def olvidar_wifi(self):
        ssid = self.combo_ssids.currentText()
        if not ssid or ssid == "Escaneando..." or ssid == "No se encontraron redes": return
        
        confirmar = QMessageBox.question(self, "Olvidar Red", f"¿Deseas eliminar el perfil de '{ssid}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirmar == QMessageBox.StandardButton.Yes:
            res = subprocess.run(['netsh', 'wlan', 'delete', 'profile', f'name={ssid}'], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
            if res.returncode == 0:
                self.consola.append(f"<span style='color: #991b1b;'>[🗑] Perfil de '{ssid}' eliminado.</span>")
            else:
                self.consola.append(f"<span style='color: orange;'>[!] No se encontró perfil previo para '{ssid}'.</span>")
    # ------------------------------------------------

    def toggle_diagnostico(self):
        if self.is_testing:
            # LOGICA DE DETENCION (STOP) con validación
            confirmar = QMessageBox.question(
                self, "Confirmar cancelación",
                "¿Estás seguro de que deseas detener el diagnóstico en curso?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if confirmar != QMessageBox.StandardButton.Yes:
                return

            self.consola.append("<br><span style='color: orange;'><b>[!] Abortando diagnóstico en curso...</b></span>")
            self.btn_iniciar.setText("Cancelando...")
            self.btn_iniciar.setEnabled(False)
            if hasattr(self, 'worker') and self.worker:
                self.worker.stop()
        else:
            # LOGICA DE INICIO (START)
            data = self.combo_iface.currentData()
            if not data: return
            iface_name = data['nombre']
            
            dominio_objetivo = self.combo_url.currentText().strip()
            if not dominio_objetivo: dominio_objetivo = "lasalleflorida.edu.ar"
                
            self.is_testing = True
            self.btn_iniciar.setText("⏹ Detener Diagnóstico")
            self.btn_iniciar.setStyleSheet("background-color: #ef4444;") # Color rojo para Stop
            
            self.combo_iface.setEnabled(False)
            self.combo_url.setEnabled(False)
            self.btn_quick_dhcp.setEnabled(False)
            self.btn_quick_static.setEnabled(False)
            self.consola.clear()
            self.panel_manual.hide()
            
            self.worker = NetworkWorker(iface_name, dominio_objetivo)
            self.worker.log_signal.connect(self.actualizar_consola)
            self.worker.solicitar_ip_manual_signal.connect(self.mostrar_panel_manual_rescate)
            self.worker.finished_signal.connect(self.diagnostico_terminado)
            self.worker.start()

    def aplicar_ip(self):
        vlan_id = self.combo_vlan.currentData()
        octeto = self.txt_octeto.text().strip()
        
        if not octeto.isdigit() or int(octeto) < 1 or int(octeto) > 254:
            QMessageBox.warning(self, "Error", "Por favor, ingrese un octeto válido (1-254).")
            return
            
        red = VLANS[vlan_id]["red"]
        ip = f"{red}.{octeto}"
        gw = f"{red}.1"
        data = self.combo_iface.currentData()
        if not data: return
        iface = data['nombre']
        
        self.panel_manual.hide()

        # Determina si estamos en medio de un test o modo rápido
        if self.is_testing and hasattr(self, 'worker') and self.worker.isRunning() and not self.worker.evento_espera.is_set():
            self.worker.ip_manual_config = {"ip": ip, "gateway": gw}
            self.worker.evento_espera.set() 
        else:
            # Standalone mode setup
            self.consola.append(f"<br><span style='color: #1e3a8a;'><b>[⚙️] Fijando IP estática {ip} en '{iface}'...</b></span>")
            QApplication.processEvents()
            subprocess.run(f'netsh interface ip set address name="{iface}" static {ip} 255.255.255.0 {gw}', shell=True, creationflags=CREATE_NO_WINDOW)
            subprocess.run(f'netsh interface ip set dns name="{iface}" static 8.8.8.8', shell=True, creationflags=CREATE_NO_WINDOW)
            subprocess.run(f'netsh interface ip add dns name="{iface}" 1.1.1.1 index=2', shell=True, creationflags=CREATE_NO_WINDOW)
            self.consola.append("<span style='color: green;'>[+] Interfaz configurada correctamente con IP Manual.</span>")

    def actualizar_consola(self, mensaje):
        self.consola.append(mensaje.replace("\n", "<br>"))
        cursor = self.consola.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.consola.setTextCursor(cursor)

    def diagnostico_terminado(self, resultados):
        self.is_testing = False
        self.btn_iniciar.setEnabled(True)
        self.btn_iniciar.setText("Iniciar Diagnóstico Completo")
        self.btn_iniciar.setStyleSheet("") # Restaura el color azul nativo
        self.combo_iface.setEnabled(True)
        self.combo_url.setEnabled(True)
        self.btn_quick_dhcp.setEnabled(True)
        self.btn_quick_static.setEnabled(True)

if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes
        myappid = 'lasalle.network.troubleshooter.1.0'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    ventana = TroubleshooterLaSalle()
    ventana.show()
    sys.exit(app.exec())