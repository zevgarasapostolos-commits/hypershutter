"""Ingest benchmark (thesis §6.7): throughput with 1 / 2 / 3 destinations and the cost of verification.

    python scripts/bench_ingest.py <card folder> <dest1> [<dest2> …]
    python scripts/bench_ingest.py --proxies <card folder> <dest>     (proxies made during the ingest)

Run k = 1 … N uses the first k destinations, each into a new project folder `bench-<k>dest-<time>`
(nothing is overwritten and nothing is skipped as already ingested). Results go to reports/bench/.
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from hypershutter.core import cards, config, ingest


def main(card_dir: str, *dests: str) -> None:
    card = cards.read_card(Path(card_dir))
    runs = []
    for k in range(1, len(dests) + 1):
        project = f"bench-{k}dest-{datetime.now():%H%M%S}"
        t0 = time.time()
        r = ingest.ingest(card, project, "cam bench", [Path(d) for d in dests[:k]], proxy="none")
        wall = time.time() - t0
        copy_s = max(d["copy_s"] for d in r.dests)
        verify_s = max(d["verify_s"] for d in r.dests)
        row = {"destinations": k, "files": r.files, "gb": round(r.bytes / 1e9, 2), "wall_s": round(wall, 1),
               "copy_s": copy_s, "verify_s": verify_s, "card_mb_s": round(r.bytes / copy_s / 1e6, 1),
               "total_written_mb_s": round(k * r.bytes / copy_s / 1e6, 1),
               "verify_share": round(verify_s / wall, 2), "safe": r.safe_to_format,
               "per_dest": [{"dest": d["root"], "write_mb_s": d["write_mb_s"], "verify_mb_s": d["verify_mb_s"]} for d in r.dests]}
        runs.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    out = config.REPO_ROOT / "reports" / "bench"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"ingest-{datetime.now():%Y%m%d-%H%M}.json"
    path.write_text(json.dumps({"card": card.path, "kind": card.kind, "runs": runs}, indent=1))
    print(f"saved: {path}")




def with_proxies(card_dir: str, dest: str) -> None:
    """Ingest to one drive with the proxy queue running in the background vs. the plain ingest."""
    from hypershutter.core import proxies
    card = cards.read_card(Path(card_dir))
    q = proxies.queue()
    q.start()
    project = f"bench-proxies-{datetime.now():%H%M%S}"
    t0 = time.time()
    r = ingest.ingest(card, project, "cam bench", [Path(dest)], proxy="prores_proxy",
                      on_verified=lambda root, rel: proxies.enqueue(q, root, [rel]))
    ingest_s = time.time() - t0
    copy_s = r.dests[0]["copy_s"]
    q.wait("proxy")
    q.stop()
    done = [j for j in q.jobs("proxy") if j.project.endswith(project)]
    from hypershutter.core.proxies import _duration
    seconds = sum(_duration(Path(j.project) / j.rel) for j in done)
    proxy_wall = max(j.finished for j in done) - min(j.started for j in done)
    row = {"files": r.files, "gb": round(r.bytes / 1e9, 2), "ingest_s": round(ingest_s, 1),
           "card_mb_s": round(r.bytes / copy_s / 1e6, 1), "proxies": len(done),
           "proxies_failed": sum(j.status == "failed" for j in done), "footage_s": round(seconds, 1),
           "proxy_wall_s": round(proxy_wall, 1), "realtime_x": round(seconds / proxy_wall, 2),
           "proxy_gb": round(sum(j.bytes_out for j in done) / 1e9, 2)}
    print(json.dumps(row), flush=True)
    out = config.REPO_ROOT / "reports" / "bench"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"ingest-proxies-{datetime.now():%Y%m%d-%H%M}.json").write_text(json.dumps(row, indent=1))


if __name__ == "__main__":
    if sys.argv[1] == "--proxies":
        with_proxies(*sys.argv[2:])
    else:
        main(*sys.argv[1:])
