$pythonPath = "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv\Scripts\python.exe"
$testPath = "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\tests"

Set-Location "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine"

# Run pytest
& $pythonPath -m pytest $testPath -v --tb=short -k "paper" 2>&1
