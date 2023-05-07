import httpx
import pandas as pd
from furl import furl
from sklearn import base


def _get_location_api(
    query_params: dict, base_url="https://volunteer.vote62.com/api/locations/"
):
    client = httpx.Client()

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

    response = client.get(url, headers=headersList)

    return response


def get_provincal_list():
    query = {"parameter": "location_province"}
    data = _get_location_api(query_params=query)
    provicincal_list = data.json()["results"]
    return provicincal_list


def get_amphur_list(province):
    query = {"parameter": "location_amphoe", "location_province": province}
    data = _get_location_api(query_params=query)
    amphur_list = data.json()["results"]
    return amphur_list


def get_tambon_list(province, amphur):
    query = {
        "parameter": "location_tambon",
        "location_province": province,
        "location_amphoe": amphur,
    }
    data = _get_location_api(query_params=query)
    tambon_list = data.json()["results"]
    return tambon_list


def get_ballot_data(province, amphur, tambon):
    query = {
        "location_province": province,
        "location_amphoe": amphur,
        "location_tambon": tambon,
    }
    data = _get_location_api(
        query_params=query, base_url="https://volunteer.vote62.com/api/divisions/"
    )
    ballot_meta = data.json()["results"][0]
    ballot_units = ballot_meta["units"]
    del ballot_meta["units"]

    return ballot_meta, ballot_units


from tqdm import tqdm


def get_ballot_data_all():
    parameters = []
    ballot_meta_all = []
    ballot_units_all = []

    ps = get_provincal_list()
    for p in tqdm(ps):
        as_ = get_amphur_list(p)
        for a in tqdm(as_):
            ts = get_tambon_list(p, a)
            for t in tqdm(ts):
                ballot_meta, ballot_units = get_ballot_data(p, a, t)
                parameters.append((p, a, t))
                ballot_meta_all.append(ballot_meta)
                ballot_units_all.append(ballot_units)
    return parameters, ballot_meta_all, ballot_units_all


if __name__ == "__main__":
    ps, metas, units = get_ballot_data_all()
