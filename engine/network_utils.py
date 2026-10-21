"""
Network Utilities for AnyLocal
Detects Local LAN IP, Tailscale IP (for cross-branch connections), and machine information.
"""

import socket
import ipaddress
import subprocess
import platform

def get_hostname():
    try:
        return socket.gethostname()
    except Exception:
        return "Unknown-PC"

def is_tailscale_ip(ip_str):
    try:
        ip = ipaddress.ip_address(ip_str)
        # Tailscale assigns addresses in the CGNAT 100.64.0.0/10 block (100.64.0.0 - 100.127.255.255)
        tailscale_net = ipaddress.ip_network("100.64.0.0/10")
        return ip in tailscale_net
    except Exception:
        return False

def get_network_interfaces():
    """
    Returns a dictionary of categorized IPs:
    {
        'tailscale': ['100.85.x.y'],
        'local': ['192.168.1.105'],
        'all': [...]
    }
    """
    detected_ips = []
    
    # Method 1: socket.getaddrinfo
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if ':' not in ip and not ip.startswith('127.'):
                if ip not in detected_ips:
                    detected_ips.append(ip)
    except Exception:
        pass

    # Method 2: UDP probe to standard internal DNS (doesn't send packets, just queries routing table)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            out_ip = s.getsockname()[0]
            if out_ip not in detected_ips and not out_ip.startswith('127.'):
                detected_ips.append(out_ip)
    except Exception:
        pass

    # Method 3: Tailscale CLI check if available
    tailscale_ips = []
    try:
        result = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=1.5)
        if result.returncode == 0:
            ts_ip = result.stdout.strip()
            if ts_ip and ts_ip not in detected_ips:
                detected_ips.append(ts_ip)
            if ts_ip and ts_ip not in tailscale_ips:
                tailscale_ips.append(ts_ip)
    except Exception:
        pass

    # Categorize
    local_ips = []
    for ip in detected_ips:
        if is_tailscale_ip(ip):
            if ip not in tailscale_ips:
                tailscale_ips.append(ip)
        else:
            if ip not in local_ips:
                local_ips.append(ip)

    return {
        "tailscale": tailscale_ips,
        "local": local_ips,
        "all": detected_ips,
        "hostname": get_hostname()
    }

def is_port_available(port, host="0.0.0.0"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False

def free_port(port):
    """If a port is held by an orphan process, terminate it to reclaim the port."""
    try:
        import psutil
        import os
        current_pid = os.getpid()
        parent_pid = os.getppid() if hasattr(os, 'getppid') else None
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr and conn.laddr.port == port and conn.pid:
                if conn.pid not in (current_pid, parent_pid):
                    try:
                        proc = psutil.Process(conn.pid)
                        print(f"[AnyLocal] Freeing port {port} from stale PID {conn.pid} ({proc.name()})")
                        proc.kill()
                        proc.wait(timeout=1.0)
                    except Exception:
                        pass
    except Exception as e:
        print(f"[AnyLocal] Error freeing port {port}: {e}")
