import asyncio
import imp
import pickle
import httpx
import pandas as pd
from furl import furl
from joblib import Memory
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

# Use joblib to cache results
memory = Memory(location=".cache", verbose=0)

# Establish SQLite connection and create table if not exists
from pathlib import Path

# add date to file name
from datetime import date

date = date.today().strftime("%Y-%m-%d")
file_path = Path(__file__).parent / f"vote62_data_{date}.sqlite"

conn = sqlite3.connect(file_path)
c = conn.cursor()
c.execute(
    """CREATE TABLE IF NOT EXISTS ballot_data
             (province TEXT, amphur TEXT, tambon TEXT, ballot_meta BLOB, ballot_units BLOB)"""
)
conn.commit()


async def _get_location_api(
    query_params: dict, base_url="https://volunteer.vote62.com/api/locations/"
):
    async with httpx.AsyncClient() as client:
        baseUrl = furl(base_url)
        baseUrl.args = query_params
        url = baseUrl.url

        headersList = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9,th;q=0.8",
            "Connection": "keep-alive",
            "Cookie": "_ga=GA1.1.1064847152.1678976403; _ga_FQSY5ZJW1Z=GS1.1.1683474870.15.1.1683475862.0.0.0",
            "DNT": "1",
            "Referer": "https://volunteer.vote62.com/apply/reserve-form/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36 Edg/112.0.1722.68",
            "X-Requested-With": "XMLHttpRequest",
            "sec-ch-ua": '"Chromium";v="112", "Microsoft Edge";v="112", "Not:A-Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "Windows",
        }

        response = await client.get(url, headers=headersList)

    return response


@memory.cache
async def get_provincal_list():
    query = {"parameter": "location_province"}
    data = await _get_location_api(query_params=query)
    provicincal_list = data.json()["results"]
    return provicincal_list


@memory.cache
async def get_amphur_list(province):
    query = {"parameter": "location_amphoe", "location_province": province}
    data = await _get_location_api(query_params=query)
    amphur_list = data.json()["results"]
    return amphur_list


@memory.cache
async def get_tambon_list(province, amphur):
    query = {
        "parameter": "location_tambon",
        "location_province": province,
        "location_amphoe": amphur,
    }
    data = await _get_location_api(query_params=query)
    tambon_list = data.json()["results"]
    return tambon_list


async def get_ballot_data(province, amphur, tambon):
    query = {
        "location_province": province,
        "location_amphoe": amphur,
        "location_tambon": tambon,
    }
    data = await _get_location_api(
        query_params=query, base_url="https://volunteer.vote62.com/api/divisions/"
    )
    ballot_meta = data.json()["results"][0]
    ballot_units = ballot_meta["units"]
    del ballot_meta["units"]

    return ballot_meta, ballot_units


async def get_ballot_data_all():
    parameters = []

    ps = await get_provincal_list()
    for p in tqdm(ps):
        as_ = await get_amphur_list(p)
        for a in tqdm(as_):
            ts = await get_tambon_list(p, a)
            for t in tqdm(ts):
                ballot_meta, ballot_units = await get_ballot_data(p, a, t)
                parameters.append((p, a, t))

                # Insert data into SQLite
                c.execute(
                    "INSERT INTO ballot_data VALUES (?, ?, ?, ?, ?)",
                    (p, a, t, pickle.dumps(ballot_meta), pickle.dumps(ballot_units)),
                )
                conn.commit()

    return parameters


async def get_ballot_data_all_batch(batch_size=10):
    ps = await get_provincal_list()

    async def process_batch(batch_tasks, batch_tasks_args):
        results = await asyncio.gather(*batch_tasks)
        for (p, a, t), (ballot_meta, ballot_units) in zip(batch_tasks_args, results):
            # Insert data into SQLite
            c.execute(
                "INSERT INTO ballot_data VALUES (?, ?, ?, ?, ?)",
                (p, a, t, pickle.dumps(ballot_meta), pickle.dumps(ballot_units)),
            )
            conn.commit()

    for p in tqdm(ps):
        as_ = await get_amphur_list(p)
        for a in tqdm(as_):
            ts = await get_tambon_list(p, a)

            tasks = []
            tasks_args = []
            for t in tqdm(ts):
                task_args = (p, a, t)
                task = asyncio.create_task(get_ballot_data(*task_args))
                tasks.append(task)
                tasks_args.append(task_args)

                if len(tasks) >= batch_size:
                    await process_batch(tasks, tasks_args)
                    tasks = []

            if tasks:
                await process_batch(tasks, tasks_args)


async def main():
    await get_ballot_data_all_batch()


# Function to fetch data from SQLite
def fetch_data_from_sqlite(province=None, amphur=None, tambon=None):
    c = conn.cursor()
    query = "SELECT * FROM ballot_data"
    conditions = []

    if province:
        conditions.append(f"province = '{province}'")
    if amphur:
        conditions.append(f"amphur = '{amphur}'")
    if tambon:
        conditions.append(f"tambon = '{tambon}'")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    c.execute(query)

    rows = c.fetchall()
    results = []

    for row in rows:
        province, amphur, tambon, ballot_meta, ballot_units = row
        results.append(
            {
                "province": province,
                "amphur": amphur,
                "tambon": tambon,
                "ballot_meta": pickle.loads(ballot_meta),
                "ballot_units": pickle.loads(ballot_units),
            }
        )

    return results


if __name__ == "__main__":
    asyncio.run(main())
    conn.close()  # Close the SQLite connection when done
