@echo off
echo 🔍 Testing LLM endpoints without authentication...
echo.

echo 📊 Testing /llm/test without auth:
curl -s http://127.0.0.1:8010/llm/test

echo.
echo 📊 Testing /llm/health without auth:
curl -s http://127.0.0.1:8010/llm/health

echo.
echo 📊 Testing /llm/chat without auth:
curl -s -H "Content-Type: application/json" -d '{"message": "Hello test"}' http://127.0.0.1:8010/llm/chat

echo.
echo 🔍 LLM testing completed
