import httpx
import pandas as pd


def get_provincal_summary():
    client = httpx.Client()

    reqUrl = "https://volunteer.vote62.com/api/volunteer-summary/"

    headersList = {
        # "Accept": "*/*",
        # "Accept-Language": "en-US,en;q=0.9,th;q=0.8",
        # "Connection": "keep-alive",
        # "DNT": "1",
        # "Origin": "https://www.vote62.com",
        # "Referer": "https://www.vote62.com/",
        # "Sec-Fetch-Dest": "empty",
        # "Sec-Fetch-Mode": "cors",
        # "Sec-Fetch-Site": "same-site",
        # "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36 Edg/112.0.1722.68",
        # "sec-ch-ua": "Chromium";v="112", "Microsoft Edge";v="112", "Not:A-Brand";v="99",
        # "sec-ch-ua-mobile": "?0",
        # "sec-ch-ua-platform": "Windows"
    }

    data = client.get(reqUrl, headers=headersList)

    data = data.json()["items"]

    df = pd.DataFrame(data)

    df.to_csv("data/source/vote62/provincal_summary.csv", index=False)


if __name__ == "__main__":
    get_provincal_summary()
