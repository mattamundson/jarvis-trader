Set-Location "C:\Users\mattm\ThinkorSwim\jarvis-trader\dashboard"

# Run the build
pnpm run build 2>&1 | Select-Object -Last 100
