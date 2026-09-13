#!/usr/bin/env bash
# ==============================================================================
# vnc.sh: 一键管理 Ubuntu 虚拟桌面 (Xvfb + openbox + x11vnc)
# 用法:
#   ./vnc.sh start   - 启动虚拟桌面和 VNC 服务（5900 端口）
#   ./vnc.sh stop    - 彻底关闭虚拟桌面和 VNC，释放资源
#   ./vnc.sh status  - 查看当前 VNC 与虚拟桌面运行状态
# ==============================================================================

set -eo pipefail

DISPLAY_NUM=":99"
VNC_PORT="5900"

case "$1" in
  start)
    echo "[VNC] 检查并清理残留进程..."
    killall -9 x11vnc openbox Xvfb 2>/dev/null || true
    rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true

    echo "[VNC] 1. 启动 Xvfb 虚拟屏幕 (${DISPLAY_NUM})..."
    Xvfb "${DISPLAY_NUM}" -screen 0 1920x1080x24 >/dev/null 2>&1 &
    sleep 2

    echo "[VNC] 2. 启动 openbox 窗口管理器..."
    DISPLAY="${DISPLAY_NUM}" openbox >/dev/null 2>&1 &
    sleep 1

    echo "[VNC] 3. 启动 x11vnc 服务 (监听端口 ${VNC_PORT})..."
    x11vnc -display "${DISPLAY_NUM}" -localhost -nopw -forever -shared >/dev/null 2>&1 &
    sleep 1

    echo "========================================================"
    echo "✅ 虚拟桌面与 VNC 服务已就绪！"
    echo "--------------------------------------------------------"
    echo "1. 本地建立 SSH 隧道（在本机执行）:"
    echo "   ssh -L 5900:127.0.0.1:5900 <user>@<server-ip>"
    echo "2. 本地 VNC 客户端连接: 127.0.0.1:5900"
    echo "3. 在服务器终端运行添加账号命令:"
    echo "   DISPLAY=:99 uv run python checkin.py add <name>"
    echo "========================================================"
    ;;

  stop)
    echo "[VNC] 正在关闭虚拟桌面和 VNC 服务..."
    killall -9 x11vnc openbox Xvfb 2>/dev/null || true
    rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true
    echo "✅ 虚拟桌面及 VNC 进程已彻底关闭，端口已释放！"
    ;;

  status)
    echo "[VNC] 当前运行状态检查:"
    if pgrep -x "Xvfb" >/dev/null && pgrep -x "x11vnc" >/dev/null; then
      echo "  • Xvfb:   运行中 (PID: $(pgrep -x Xvfb | tr '\n' ' '))"
      echo "  • openbox: $(pgrep -x openbox >/dev/null && echo '运行中' || echo '未启动')"
      echo "  • x11vnc: 运行中 (PID: $(pgrep -x x11vnc | tr '\n' ' '))"
      echo "  • 状态:   ✅ 正在监听 127.0.0.1:5900"
    else
      echo "  • 状态:   ❌ 未运行 (已停止)"
    fi
    ;;

  *)
    echo "用法: $0 {start|stop|status}"
    echo "  start   一键启动 Xvfb + openbox + x11vnc"
    echo "  stop    一键关闭并清理残留进程"
    echo "  status  检查运行状态"
    exit 1
    ;;
esac
