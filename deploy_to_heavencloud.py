import os
import sys
import getpass
import paramiko
from typing import Optional

# Ensure UTF-8 output on Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def get_vps_ip() -> str:
    ip = os.getenv("VPS_IP")
    if ip:
        return ip
    cfg_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if os.path.exists(cfg_file):
        try:
            import json
            with open(cfg_file, "r", encoding="utf-8") as f:
                c = json.load(f)
                if c.get("static_ip"):
                    return c["static_ip"]
        except Exception:
            pass
    return "your_vps_ip_here"

VPS_IP = get_vps_ip()
VPS_PORT = 22
VPS_USER = "root"
REMOTE_DIR = "/root/nifty_3point_algo"
LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))

def deploy(password: Optional[str] = None):
    print("=" * 70)
    print(f"[*] Deploying NIFTY 3-Point Scalper Bot to HeavenCloud VPS ({VPS_IP})")
    print(f"    Target Folder : {REMOTE_DIR}")
    print(f"    Target Port   : 8002 (Isolated from Port 8000 and 8001)")
    print("=" * 70)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        if password:
            client.connect(VPS_IP, port=VPS_PORT, username=VPS_USER, password=password, timeout=10)
        else:
            try:
                client.connect(VPS_IP, port=VPS_PORT, username=VPS_USER, timeout=5)
            except paramiko.AuthenticationException:
                pwd = getpass.getpass(f"Enter root password for {VPS_IP}: ")
                client.connect(VPS_IP, port=VPS_PORT, username=VPS_USER, password=pwd, timeout=10)
    except Exception as e:
        print(f"[ERROR] SSH Connection Failed: {e}")
        return False

    print("[SUCCESS] SSH Connection established as root!")

    # 1. Create remote directory tree
    subdirs = [
        "",
        "nifty_algo",
        "nifty_algo/config",
        "nifty_algo/data",
        "nifty_algo/indicators",
        "nifty_algo/market_structure",
        "nifty_algo/liquidity",
        "nifty_algo/patterns",
        "nifty_algo/strategies",
        "nifty_algo/confidence",
        "nifty_algo/option_selector",
        "nifty_algo/execution",
        "nifty_algo/risk",
        "nifty_algo/position_manager",
        "nifty_algo/post_target_logger",
        "nifty_algo/analytics",
        "nifty_algo/database",
        "nifty_algo/notifications",
        "nifty_algo/monitoring",
        "nifty_algo/backtesting",
        "tests"
    ]
    for d in subdirs:
        client.exec_command(f"mkdir -p {REMOTE_DIR}/{d}")

    # 2. Upload files via SFTP
    sftp = client.open_sftp()

    def upload_dir(local_path, remote_path):
        for item in os.listdir(local_path):
            l_item = os.path.join(local_path, item)
            r_item = f"{remote_path}/{item}"
            if os.path.isdir(l_item):
                if item in ("__pycache__", ".pytest_cache", ".git"):
                    continue
                try:
                    sftp.mkdir(r_item)
                except Exception:
                    pass
                upload_dir(l_item, r_item)
            else:
                if item.endswith((".pyc", ".db")):
                    continue
                print(f"  Uploading {item} -> {r_item}")
                sftp.put(l_item, r_item)

    print("[SFTP] Syncing project files...")
    upload_dir(os.path.join(LOCAL_DIR, "nifty_algo"), f"{REMOTE_DIR}/nifty_algo")
    upload_dir(os.path.join(LOCAL_DIR, "tests"), f"{REMOTE_DIR}/tests")

    root_files = [
        "main.py",
        "config.json",
        "SUU388config.json",
        "requirements.txt",
        "nifty_algo.service",
        "README.md",
        "run_opportunity_comparison.py",
        "opportunity_comparison_results.json",
        "opportunity_mode_trades.csv",
        "run_six_engine_comparison.py",
        "six_engine_comparison_results.json",
        "six_engine_combined_trades.csv"
    ]
    for rf in root_files:
        l_path = os.path.join(LOCAL_DIR, rf)
        if os.path.exists(l_path):
            print(f"  Uploading {rf} -> {REMOTE_DIR}/{rf}")
            sftp.put(l_path, f"{REMOTE_DIR}/{rf}")

    sftp.close()
    print("[SUCCESS] All files uploaded.")

    # 3. Virtual environment package verification
    print("[PACKAGES] Checking dependencies in /root/nifty_3point_algo/venv...")
    stdin, stdout, stderr = client.exec_command(
        f"/root/nifty_3point_algo/venv/bin/pip install -q fastapi 'uvicorn[standard]' kiteconnect pandas numpy websockets requests pytest 2>&1"
    )
    stdout.channel.recv_exit_status()

    # 4. Install systemd service
    print("[SYSTEMD] Configuring /etc/systemd/system/nifty_algo.service ...")
    client.exec_command(f"cp {REMOTE_DIR}/nifty_algo.service /etc/systemd/system/nifty_algo.service")

    # 5. Reload, enable & start service
    print("[SERVICE] Restarting nifty_algo service on port 8002...")
    commands = [
        "systemctl daemon-reload",
        "systemctl enable nifty_algo",
        "systemctl restart nifty_algo",
        "sleep 2",
        "systemctl status nifty_algo --no-pager"
    ]
    stdin, stdout, stderr = client.exec_command(" && ".join(commands))
    print(stdout.read().decode())

    # 6. Verify port
    stdin, stdout, stderr = client.exec_command("ss -tulpn | grep 8002 || netstat -tulpn | grep 8002")
    port_out = stdout.read().decode().strip()
    if port_out:
        print(f"[PORT] Port 8002 is ACTIVE & LISTENING: {port_out}")
    else:
        print("[INFO] Checking process table...")
        stdin, stdout, stderr = client.exec_command("ps aux | grep 'main.py' | grep -v grep")
        print(stdout.read().decode())

    client.close()
    print("=" * 70)
    print("DEPLOYMENT COMPLETE!")
    print(f"   Dashboard URL : http://{VPS_IP}:8002/")
    print(f"   API Status    : http://{VPS_IP}:8002/api/status")
    print(f"   Analytics API : http://{VPS_IP}:8002/api/analytics")
    print("=" * 70)
    return True

if __name__ == "__main__":
    pwd_arg = sys.argv[1] if len(sys.argv) > 1 else None
    deploy(password=pwd_arg)
