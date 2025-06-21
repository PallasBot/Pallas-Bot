from pyncm_async import apis as ncm


async def get_song_id(song_name: str):
    if not song_name:
        return None
    if song_name.isdigit():
        return song_name

    res = await ncm.cloudsearch.GetSearchResult(song_name, 1, 10)
    if "result" not in res or "songCount" not in res["result"]:
        return None

    if res["result"]["songCount"] == 0:
        return None

    for song in res["result"]["songs"]:
        privilege = song["privilege"]
        if "chargeInfoList" not in privilege:
            continue

        charge_info_list = privilege["chargeInfoList"]
        if len(charge_info_list) == 0:
            continue

        if charge_info_list[0]["chargeType"] == 1:
            continue

        return song["id"]

    return None


async def get_song_title(song_id):
    response = await ncm.track.GetTrackDetail(song_id)
    return response["songs"][0]["name"]
