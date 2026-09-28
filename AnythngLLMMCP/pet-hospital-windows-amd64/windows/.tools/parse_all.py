import ast
from pathlib import Path
for path in list(Path('pet_hospital_mcp/src').rglob('*.py')) + list(Path('pet_hospital_mcp/tests').rglob('*.py')):
    ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    print(f'OK {path}')
