import time
import tempfile
import shutil
from pathlib import Path
from swampcastle.services.vault import VaultService
from swampcastle.wal import WalWriter
from swampcastle.storage.memory import InMemoryStorageFactory
from swampcastle.models.drawer import AddDrawerCommand


def make_vault_with_drawers(n: int, tmpdir: Path, mult: int = 50):
    factory = InMemoryStorageFactory()
    wal = WalWriter(tmpdir / "wal")
    vault = VaultService(factory.open_collection("swampcastle_chests"), wal)

    for i in range(n):
        content = ("This is document " + str(i) + ". ") * mult
        cmd = AddDrawerCommand(wing="bench", room="r1", content=content)
        vault.add_drawer(cmd)
    return vault


def run_bench(n: int = 1000, workers: int | None = None, mult: int = 50):
    tmp = Path(tempfile.mkdtemp())
    try:
        vault = make_vault_with_drawers(n, tmp, mult=mult)
        # Run sequential
        t0 = time.perf_counter()
        cnt_seq = vault.distill(parallel_workers=None)
        t1 = time.perf_counter()
        # Run parallel
        t2 = time.perf_counter()
        cnt_par = vault.distill(parallel_workers=workers)
        t3 = time.perf_counter()
        print(f"N={n}, mult={mult}, sequential: {t1-t0:.3f}s, parallel({workers}): {t3-t2:.3f}s, cnt_seq={cnt_seq}, cnt_par={cnt_par}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("-n", type=int, default=1000)
    p.add_argument("-w", type=int, default=4)
    p.add_argument("-m", type=int, default=50)
    args = p.parse_args()
    run_bench(n=args.n, workers=args.w, mult=args.m)
