# -*- coding: utf-8 -*-
"""按命令行特征结束本项目的 app.py / serve_demo.py 服务器进程（原生调用，规避 git-bash 的路径/参数改写）。

用途：验收脚本启动服务器前先清场，避免「端口被占用 → 探针打到别的库 → 结论失真」。

**安全口径（2026-10-03 修）**：
  * 带 `--port N` → **只杀**「命令行含 app.py/serve_demo.py 且正在监听 N」的进程；
  * 不带 `--port` → 名称匹配，但**跳过常驻演示服务**（监听 5000 的那个，由计划任务
    `Hermes_Demo_Zhongyi_5000` 托管），避免验收清场把演示站点一起杀掉；
  * 需要连常驻服务一起杀时显式加 `--include-persistent`。

用法：
  python tools/kill_app_servers.py --port 5085        # 清掉 5085 上的本项目服务器（验收常用）
  python tools/kill_app_servers.py                    # 名称清场，但保护 :5000 常驻服务
  python tools/kill_app_servers.py --include-persistent
"""
import subprocess
import sys
import time

PERSISTENT_PORT = 5000


def app_pids():
    q = subprocess.run(["wmic", "process", "where", "name like '%python%'", "get", "processid,commandline",
                        "/format:csv"], capture_output=True, text=True, errors="replace")
    pids = []
    for line in (q.stdout or "").splitlines():
        if ("app.py" not in line and "serve_demo.py" not in line) or line.startswith("Node"):
            continue
        tail = line.rstrip().rsplit(",", 1)
        if len(tail) == 2 and tail[1].strip().isdigit():
            pids.append(int(tail[1]))
    return pids


def listening_pids(ports):
    """给定端口上处于 LISTENING 的 pid 集合。"""
    ports = {str(p) for p in ports}
    n = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, errors="replace")
    holders = set()
    for line in (n.stdout or "").splitlines():
        if "LISTENING" not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        if parts[1].rsplit(":", 1)[-1] in ports and parts[-1].isdigit():
            holders.add(int(parts[-1]))
    return holders


def parent_map():
    """{pid: ppid}（用于把「监听者的父进程」也纳入保护：taskkill /T 会连树一起杀）。"""
    q = subprocess.run(["wmic", "process", "get", "processid,parentprocessid", "/format:csv"],
                       capture_output=True, text=True, errors="replace")
    out = {}
    for line in (q.stdout or "").splitlines():
        parts = line.strip().split(",")
        if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
            out[int(parts[-1])] = int(parts[-2])
    return out


def main():
    args = sys.argv[1:]
    ports = [args[i + 1] for i, a in enumerate(args) if a == "--port" and len(args) > i + 1]
    include_persistent = "--include-persistent" in args
    candidates = app_pids()

    protected = set()
    if not include_persistent:
        listeners = listening_pids({PERSISTENT_PORT})
        parents = parent_map()
        protected = set(listeners)
        for pid in listeners:                     # 父进程（venv 启动器）也必须保护，否则 /T 连树杀掉
            ppid = parents.get(pid)
            if ppid:
                protected.add(ppid)
    if protected:
        print("保护常驻演示服务（:%d）及其父进程，pid %s：如需一起清掉请加 --include-persistent"
              % (PERSISTENT_PORT, ",".join(str(p) for p in sorted(protected))))

    if ports:
        holders = listening_pids(ports)
        targets = [p for p in candidates if p in holders]
        skipped = [p for p in candidates if p not in holders]
        print("端口 %s 上的本项目服务器：%s" % (",".join(ports), targets or "无"))
        if skipped:
            print("  跳过（不在这些端口上）：%s" % skipped)
    else:
        targets = [p for p in candidates if p not in protected]
        if not candidates:
            print("未发现 app.py / serve_demo.py 进程")

    for pid in targets:
        r = subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True, text=True, errors="replace")
        ok = r.returncode == 0 or "PID" in (r.stdout or "")
        print("  结束 PID %s：%s" % (pid, "成功" if ok else (r.stdout or r.stderr).strip()[:60]))
    time.sleep(2)

    for port in ports:
        left = listening_pids([port])
        print("端口 %s 清场后：%s" % (port, "已释放" if not left else "仍被占用 pid=%s" % sorted(left)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
