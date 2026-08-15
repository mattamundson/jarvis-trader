#!/bin/bash
# Advanced Jarvis Trading System Monitor
# Monitors all critical components and sends alerts

echo "🔍 Jarvis Trading System Monitor - $(date)"
echo "============================================"

# Check engine health
echo "📊 Engine Health Check:"
engine_health=$(curl -s http://127.0.0.1:8010/health 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "✅ Engine: Online"
    # Extract key metrics
    echo "   Status: $(echo $engine_health | jq -r '.status')"
    echo "   Kill Switch: $(echo $engine_health | jq -r '.kill_switch_active')"
    echo "   IBKR Connected: $(echo $engine_health | jq -r '.ibkr_connected')"
    echo "   TradingView MCP: $(echo $engine_health | jq -r '.tradingview_mcp_healthy')"
    
    # Check LLM provider status
    llm_providers=$(echo $engine_health | jq -r '.llm_providers')
    echo "   LLM Active: $(echo $llm_providers | jq -r '.active_provider')"
    echo "   LLM Primary: $(echo $llm_providers | jq -r '.primary_provider')"
    echo "   LLM Primary Healthy: $(echo $llm_providers | jq -r '.primary_healthy')"
else
    echo "❌ Engine: Offline or unreachable"
fi

echo ""
echo "📊 Dashboard Health Check:"
dashboard_health=$(curl -s http://127.0.0.1:3010 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "✅ Dashboard: Online"
    dashboard_size=$(echo $dashboard_health | wc -c)
    echo "   Response Size: ${dashboard_size} bytes"
else
    echo "❌ Dashboard: Offline or unreachable"
fi

echo ""
echo "📊 PM2 Process Status:"
pm2_status=$(pm2 list 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "✅ PM2: Running"
    echo "   Jarvis Engine: $(echo "$pm2_status" | grep jarvis-engine | awk '{print $8, $9}')"
    echo "   Jarvis Dashboard: $(echo "$pm2_status" | grep jarvis-dashboard | awk '{print $8, $9}')"
    echo "   Jarvis Bridge API: $(echo "$pm2_status" | grep jarvis-bridge-api | awk '{print $8, $9}')"
else
    echo "❌ PM2: Not running"
fi

echo ""
echo "📊 System Resources:"
echo "   CPU Usage: $(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | sed 's/%us,//')"
echo "   Memory Usage: $(free -m | awk '/Mem:/ {printf "%.1f%%", $3/$2*100}')"
echo "   Disk Usage: $(df -h / | awk 'NR==2 {print $5}')"

echo ""
echo "📊 Network Connectivity:"
echo "   IBKR Port: $(netstat -an | grep :4002 | grep LISTENing | wc -l | awk '{print $1}')"
echo "   Engine Port: $(netstat -an | grep :8010 | grep LISTENing | wc -l | awk '{print $1}')"
echo "   Dashboard Port: $(netstat -an | grep :3010 | grep LISTENing | wc -l | awk '{print $1}')"
echo "   TradingView CDP: $(netstat -an | grep :9222 | grep LISTENing | wc -l | awk '{print $1}')"

echo ""
echo "📊 Recent Decisions:"
recent_decisions=$(curl -s http://127.0.0.1:8010/decisions/recent 2>/dev/null)
if [ $? -eq 0 ]; then
    decision_count=$(echo "$recent_decisions" | jq -r '.data | length' 2>/dev/null || echo "N/A")
    echo "   Recent Decisions: $decision_count"
    
    if [ "$decision_count" != "0" ] && [ "$decision_count" != "N/A" ]; then
        latest_decision=$(echo "$recent_decisions" | jq -r '.data[0].symbol' 2>/dev/null || echo "N/A")
        echo "   Latest: $latest_decision"
    fi
else
    echo "   Recent Decisions: N/A (API error)"
fi

echo ""
echo "🔍 Monitor completed at $(date)"
echo "============================================"
