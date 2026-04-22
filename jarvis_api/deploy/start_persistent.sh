#!/bin/bash
# Start JARVIS API Bridge persistently via supervisor
# Usage: ./start_persistent.sh [start|stop|restart|status|logs]

WORK_DIR="/home/user/workspace/jarvis_api"
CONF="$WORK_DIR/deploy/supervisor.conf"
LOG_DIR="$WORK_DIR/logs"
CMD=${1:-start}

mkdir -p "$LOG_DIR"

case "$CMD" in
  start)
    echo "Starting JARVIS API Bridge..."
    supervisord -c "$CONF"
    sleep 2
    supervisorctl -c "$CONF" status
    echo ""
    echo "API Health Check:"
    curl -s http://localhost:8020/health | python3 -m json.tool 2>/dev/null || echo "Starting up..."
    ;;
  stop)
    supervisorctl -c "$CONF" stop jarvis_api
    supervisorctl -c "$CONF" shutdown
    echo "JARVIS API stopped."
    ;;
  restart)
    supervisorctl -c "$CONF" restart jarvis_api
    sleep 2
    supervisorctl -c "$CONF" status
    ;;
  status)
    supervisorctl -c "$CONF" status
    echo ""
    curl -s http://localhost:8020/health | python3 -m json.tool 2>/dev/null || echo "API not responding"
    ;;
  logs)
    tail -f "$LOG_DIR/jarvis_api.log"
    ;;
  install-systemd)
    echo "Installing systemd service..."
    sudo cp "$WORK_DIR/deploy/jarvis-api.service" /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable jarvis-api
    sudo systemctl start jarvis-api
    sudo systemctl status jarvis-api
    ;;
  install-cron)
    echo "Installing watchdog cron (runs every minute)..."
    (crontab -l 2>/dev/null; echo "* * * * * $WORK_DIR/deploy/watchdog.sh") | crontab -
    echo "Cron installed:"
    crontab -l
    ;;
  *)
    echo "Usage: $0 [start|stop|restart|status|logs|install-systemd|install-cron]"
    ;;
esac
