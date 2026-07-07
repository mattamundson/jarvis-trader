with open("engine/main.py") as f:
    lines = f.readlines()
    for i, line in enumerate(lines[:150]):
        print(f"{i+1:3}: {line.rstrip()}")
