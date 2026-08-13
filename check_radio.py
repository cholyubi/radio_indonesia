import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# KONFIGURASI
# ==========================================

FILE_INPUT = (
    "https://raw.githubusercontent.com/"
    "cholyubi/radio_indonesia/main/radio_indonesia.m3u"
)

FILE_OUTPUT = "radio_indonesia_online.m3u"

MAX_THREADS = 20
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 15
RETRY_COUNT = 3

HEADERS_STREAM = {
    "User-Agent": "VLC/3.0.16 LibVLC/3.0.16",
    "Icy-MetaData": "1"
}


# ==========================================
# DOWNLOAD PLAYLIST
# ==========================================

def download_playlist():

    print("Mengunduh playlist master...")

    r = requests.get(
        FILE_INPUT,
        timeout=30
    )

    r.raise_for_status()

    return r.text.splitlines()


# ==========================================
# PARSE PLAYLIST
# ==========================================

def parse_playlist(lines):

    radios = []
    extinf = None

    for line in lines:

        line = line.strip()

        if not line:
            continue

        if line.startswith("#EXTINF"):

            extinf = line
            continue

        if extinf and line.startswith(("http://", "https://")):

            radios.append(
                (extinf, line)
            )

            extinf = None

    return radios


# ==========================================
# CEK STREAM
# ==========================================

def check_stream(extinf, url):

    name = extinf.split(",", 1)[-1].strip()

    for attempt in range(RETRY_COUNT):

        try:

            start = time.perf_counter()

            r = requests.get(
                url,
                headers=HEADERS_STREAM,
                stream=True,
                timeout=(
                    CONNECT_TIMEOUT,
                    READ_TIMEOUT
                ),
                allow_redirects=True
            )

            latency = round(
                (time.perf_counter() - start) * 1000
            )

            if r.status_code not in (200, 206):

                r.close()
                continue

            # Ambil sedikit data untuk memastikan
            # server benar-benar mengirim stream
            chunk = next(
                r.iter_content(1024),
                None
            )

            r.close()

            if chunk and len(chunk) > 0:

                return {
                    "name": name,
                    "extinf": extinf,
                    "url": url,
                    "online": True,
                    "latency": latency
                }

        except Exception:
            pass

    return {
        "name": name,
        "extinf": extinf,
        "url": url,
        "online": False,
        "latency": None
    }


# ==========================================
# MAIN
# ==========================================

def main():

    try:

        lines = download_playlist()

    except Exception as e:

        print("Gagal download playlist:")
        print(e)

        return

    radios = parse_playlist(lines)

    total = len(radios)

    print()
    print(f"Total radio ditemukan : {total}")
    print(f"Thread                : {MAX_THREADS}")
    print()

    online_radios = []

    online_count = 0
    offline_count = 0
    checked = 0

    with ThreadPoolExecutor(
        max_workers=MAX_THREADS
    ) as executor:

        futures = [
            executor.submit(
                check_stream,
                extinf,
                url
            )
            for extinf, url in radios
        ]

        for future in as_completed(futures):

            result = future.result()

            checked += 1

            if result["online"]:

                online_count += 1
                online_radios.append(result)

                print(
                    f"[{checked}/{total}] "
                    f"+ ONLINE "
                    f"{result['name']} "
                    f"({result['latency']} ms)"
                )

            else:

                offline_count += 1

                print(
                    f"[{checked}/{total}] "
                    f"x OFFLINE "
                    f"{result['name']}"
                )

    # ======================================
    # SORTIR BERDASARKAN NAMA
    # ======================================

    online_radios.sort(
        key=lambda x: x["name"].lower()
    )

    # ======================================
    # TULIS PLAYLIST HASIL
    # ======================================

    with open(
        FILE_OUTPUT,
        "w",
        encoding="utf-8"
    ) as f:

        f.write("#EXTM3U\n")

        for radio in online_radios:

            f.write(
                radio["extinf"] + "\n"
            )

            f.write(
                radio["url"] + "\n"
            )

    # ======================================
    # LAPORAN
    # ======================================

    print()
    print("=" * 60)
    print("LAPORAN HASIL")
    print("=" * 60)

    print(f"Total Dicek     : {total}")
    print(f"Total Online    : {online_count}")
    print(f"Total Offline   : {offline_count}")
    print(f"Playlist        : {FILE_OUTPUT}")

    print("=" * 60)


if __name__ == "__main__":
    main()
