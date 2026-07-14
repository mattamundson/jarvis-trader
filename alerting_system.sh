#!/bin/bash
# Jarvis Trading System Alerting
# Sends alerts when critical issues are detected

ALERT_THRESHOLD_CPU=80
ALERT_THRESHOLD_MEMORY=85
ALERT_THRESHOLD_DISK=90

echo "🚨 Jarvis Trading System Alerting - $(date)"
echo "============================================"

# Check engine health
engine_health=$(curl -s http://127.0.0.1:8010/health 2>/dev/null)
if [ $? -ne 0 ]; then
    echo "🚨 CRITICAL: Engine is offline!"
    echo "   Action: Restart engine immediately"
    # Send alert (could be email, Slack, Telegram, etc.)
    echo "   Alert: Engine offline - $(date)" | tee -a /tmp/jarvis_alerts.log
fi

# Check if kill switch is active
kill_switch=$(echo "$engine_health" | jq -r '.kill_switch_active' 2>/dev/null)
if [ "$kill_switch" = "true" ]; then
    echo "🚨 CRITICAL: Kill switch is active!"
    echo "   Action: Check if this is intentional or needs deactivation"
    echo "   Alert: Kill switch active - $(date)" | tee -a /tmp/jarvis_alerts.log
fi

# Check LLM provider health
primary_healthy=$(echo "$engine_health" | jq -r '.llm_providers.primary_healthy' 2>/dev/null)
if [ "$primary_healthy" = "false" ]; then
    echo "🚨 WARNING: Primary LLM provider is unhealthy"
    echo "   Action: Check LLM provider configuration"
    echo "   Alert: LLM provider unhealthy - $(date)" | tee -a /tmp/jarvis_alerts.log
fi

# Check IBKR connection
ibkr_connected=$(echo "$engine_health" | jq -r '.ibkr_connected' 2>/dev/null)
if [ "$ibkr_connected" = "false" ]; then
    echo "🚨 CRITICAL: IBKR connection lost!"
    echo "   Action: Check IBKR connection and credentials"
    echo "   Alert: IBKR connection lost - $(date)" | tee -a /tmp/jarvis_alerts.log
fi

# Check dashboard
dashboard_health=$(curl -s http://127.0.0.1:3010 2>/dev/null)
if [ $? -ne 0 ]; then
    echo "🚨 WARNING: Dashboard is offline"
    echo "   Action: Check dashboard service"
    echo "   Alert: Dashboard offline - $(date)" | tee -a /tmp/jarvis_alerts.log
fi

# Check system resources
cpu_usage=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | sed 's/%us,//' | cut -d. -f1)
if [ "$cpu_usage" -gt "$ALERT_THRESHOLD_CPU" ]; then
    echo "🚨 WARNING: High CPU usage: ${cpu_usage}%"
    echo "   Action: Check for resource-intensive processes"
    echo "   Alert: High CPU usage - $(date)" | tee -a /tmp/jarvis_alerts.log
fi

memory_usage=$(free -m | awk '/Mem:/ {printf "%.0f", $3/$2*100}')
if [ "$memory_usage" -gt "$ALERT_THRESHOLD_MEMORY" ]; then
    echo "🚨 WARNING: High memory usage: ${memory_usage}%"
    echo "   Action: Check memory usage and optimize"
    echo "   Alert: High memory usage - $(date)" | tee -a /tmp/jarvis_alerts.log
fi

echo ""
echo "📊 Alert check completed at $(date)"
echo "============================================"
