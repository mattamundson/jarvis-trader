"""
Re-registers Jarvis-HealthWatchdog task with WorkingDirectory set.
Run once from any directory.
"""
import os
import re
import subprocess
import tempfile

r = subprocess.run(
    ["schtasks.exe", "/Query", "/TN", "Jarvis-HealthWatchdog", "/XML"],
    capture_output=True,
    text=True,
)
xml = r.stdout

old = "<Arguments>-m engine.scripts.health_watchdog</Arguments>"
wd = "C:\\Users\\mattm\\ThinkorSwim\\jarvis-trader"
insert = old + "\n      <WorkingDirectory>" + wd + "</WorkingDirectory>"
xml_new = xml.replace(old, insert)

m = re.search(r"<Exec>(.*?)</Exec>", xml_new, re.DOTALL)
if m:
    print("Exec section after patch:")
    print(m.group(0))

tmp_path = os.path.join(tempfile.gettempdir(), "jarvis_healthwatchdog_task.xml")
with open(tmp_path, "w", encoding="utf-16") as f:
    f.write(xml_new)

r2 = subprocess.run(
    ["schtasks.exe", "/Create", "/TN", "Jarvis-HealthWatchdog", "/XML", tmp_path, "/F"],
    capture_output=True,
    text=True,
)
print("STDOUT:", r2.stdout)
print("STDERR:", r2.stderr)
print("RC:", r2.returncode)
