import requests
import time
import re
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
# AMBIL NAMA RADIO
# ==========================================

def get_radio_name(extinf):

    return extinf.split(",", 1)[-1].strip()


# ==========================================
# NORMALISASI NAMA RADIO
# ==========================================

def normalize_name(name):

    name = name.lower().strip()

    # Hilangkan karakter yang tidak penting
    name = re.sub(r"[^a-z0-9]+", " ", name)

    # Hilangkan spasi berlebih
    name = re.sub(r"\s+", " ", name)

    return name.strip()


# ==========================================
# KELOMPOKKAN STASIUN
# ==========================================

def group_stations(radios):

    stations = {}

    for extinf, url in radios:

        name = get_radio_name(extinf)

        station_key = normalize_name(name)

        if station_key not in stations:

            stations[station_key] = {
                "name": name,
                "entries": []
            }

        stations[station_key]["entries"].append(
            {
                "extinf": extinf,
                "url": url
            }
        )

    return stations


# ==========================================
# HAPUS URL DUPLIKAT
# ==========================================

def remove_duplicate_urls(stations):

    for station in stations.values():

        seen_urls = set()
        unique_entries = []

        for entry in station["entries"]:

            url = entry["url"].strip().rstrip("/")

            if url in seen_urls:
                continue

            seen_urls.add(url)

            unique_entries.append(entry)

        station["entries"] = unique_entries


# ==========================================
# CEK STREAM
# ==========================================

def check_stream(extinf, url):

    name = get_radio_name(extinf)

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

            # Ambil sedikit data
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

    # ======================================
    # DOWNLOAD PLAYLIST
    # ======================================

    try:

        lines = download_playlist()

    except Exception as e:

        print("Gagal download playlist:")
        print(e)

        return


    # ======================================
    # PARSE
    # ======================================

    radios = parse_playlist(lines)

    total_entries = len(radios)

    print()
    print(f"Total entry playlist : {total_entries}")


    # ======================================
    # KELOMPOKKAN STASIUN
    # ======================================

    stations = group_stations(radios)

    total_stations = len(stations)

    # Hilangkan URL yang sama
    remove_duplicate_urls(stations)

    print(
        f"Stasiun unik         : {total_stations}"
    )

    print(
        f"Thread               : {MAX_THREADS}"
    )

    print()


    # ======================================
    # SIAPKAN SEMUA URL UNTUK DICEK
    # ======================================

    jobs = []

    for station_key, station in stations.items():

        for entry in station["entries"]:

            jobs.append(
                (
                    station_key,
                    entry["extinf"],
                    entry["url"]
                )
            )


    total_urls = len(jobs)

    print(
        f"Total URL yang dicek : {total_urls}"
    )

    print()


    # ======================================
    # CEK SEMUA STREAM
    # ======================================

    results = []

    checked = 0

    with ThreadPoolExecutor(
        max_workers=MAX_THREADS
    ) as executor:

        futures = {}

        for station_key, extinf, url in jobs:

            future = executor.submit(
                check_stream,
                extinf,
                url
            )

            futures[future] = station_key


        for future in as_completed(futures):

            station_key = futures[future]

            result = future.result()

            result["station_key"] = station_key

            results.append(result)

            checked += 1


            if result["online"]:

                print(
                    f"[{checked}/{total_urls}] "
                    f"+ ONLINE  "
                    f"{result['name']} "
                    f"({result['latency']} ms)"
                )

            else:

                print(
                    f"[{checked}/{total_urls}] "
                    f"x OFFLINE "
                    f"{result['name']}"
                )


    # ======================================
    # KELOMPOKKAN HASIL BERDASARKAN STASIUN
    # ======================================

    station_results = {}

    for result in results:

        key = result["station_key"]

        if key not in station_results:

            station_results[key] = []

        station_results[key].append(result)


    # ======================================
    # PILIH URL TERBAIK
    # ======================================

    selected_radios = []

    offline_stations = 0

    duplicate_stations = 0

    for station_key, station in station_results.items():

        online = [
            x
            for x in station
            if x["online"]
        ]


        # ----------------------------------
        # SEMUA URL OFFLINE
        # ----------------------------------

        if not online:

            offline_stations += 1

            continue


        # ----------------------------------
        # ADA LEBIH DARI SATU URL
        # ----------------------------------

        if len(station) > 1:

            duplicate_stations += 1

            print()
            print(
                f"[STASIUN] {online[0]['name']}"
            )

            for item in station:

                if item["online"]:

                    print(
                        f"  ONLINE  "
                        f"{item['url']} "
                        f"({item['latency']} ms)"
                    )

                else:

                    print(
                        f"  OFFLINE "
                        f"{item['url']}"
                    )


        # ----------------------------------
        # PILIH LATENCY TERENDAH
        # ----------------------------------

        best = min(
            online,
            key=lambda x: x["latency"]
        )

        selected_radios.append(best)

        if len(station) > 1:

            print(
                f"  -> DIPILIH "
                f"{best['url']} "
                f"({best['latency']} ms)"
            )


    # ======================================
    # SORTIR NAMA RADIO
    # ======================================

    selected_radios.sort(
        key=lambda x: x["name"].lower()
    )


    # ======================================
    # TULIS PLAYLIST
    # ======================================

    with open(
        FILE_OUTPUT,
        "w",
        encoding="utf-8"
    ) as f:

        f.write("#EXTM3U\n")

        for radio in selected_radios:

            f.write(
                radio["extinf"] + "\n"
            )

            f.write(
                radio["url"] + "\n"
            )


    # ======================================
    # HITUNG STATISTIK
    # ======================================

    online_stations = len(selected_radios)

    offline_count = total_urls - sum(
        1
        for result in results
        if result["online"]
    )


    # ======================================
    # LAPORAN
    # ======================================

    print()
    print("=" * 60)
    print("LAPORAN HASIL")
    print("=" * 60)

    print(
        f"Total entry awal     : {total_entries}"
    )

    print(
        f"Stasiun unik         : {total_stations}"
    )

    print(
        f"Total URL dicek      : {total_urls}"
    )

    print(
        f"Stasiun punya >1 URL : {duplicate_stations}"
    )

    print(
        f"Stasiun offline      : {offline_stations}"
    )

    print(
        f"Stasiun online       : {online_stations}"
    )

    print(
        f"URL offline          : {offline_count}"
    )

    print(
        f"Playlist             : {FILE_OUTPUT}"
    )

    print("=" * 60)


# ==========================================
# RUN
# ==========================================

if __name__ == "__main__":
    main()
