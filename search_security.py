import os, re

search_dir = r'c:\Denumrutham\backend\app'
pattern = re.compile(r'def create_access_token', re.IGNORECASE)

results = []
for root, dirs, files in os.walk(search_dir):
    for file in files:
        if file.endswith('.py'):
            path = os.path.join(root, file)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    for i, line in enumerate(f, 1):
                        if pattern.search(line):
                            results.append((path, i, line.strip()))
            except Exception:
                pass

print(f"Found {len(results)} occurrences:")
for r in results:
    print(f"{r[0]}:{r[1]} -> {r[2]}")
