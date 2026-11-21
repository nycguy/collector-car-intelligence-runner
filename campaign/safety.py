from pathlib import Path
FORBIDDEN_NAMES={"credentials.json","service-account.json",".env","snapshot.csv","transactions.csv"}
def disclosure_scan(root:str):
    return [str(p) for p in Path(root).rglob("*") if p.is_file() and (p.name in FORBIDDEN_NAMES or p.suffix in {".xlsx",".xls"})]
