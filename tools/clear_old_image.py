import pymongo

mongo_client = pymongo.MongoClient("127.0.0.1", 27017, unicode_decode_error_handler="ignore")

mongo_db = mongo_client["PallasBot"]

message_mongo = mongo_db["message"]
context_mongo = mongo_db["context"]


query = {"answers.keywords": {"$regex": "\\[CQ\\:image.*url="}}
all_old_answers = context_mongo.find(query)
index = 0
for old_answers in all_old_answers:
    new_answers = []
    for answer in old_answers["answers"]:
        if "url=" in answer["keywords"] or "is_origin=" in answer["keywords"]:
            continue
        new_answers.append(answer)
    context_mongo.update_one({"_id": old_answers["_id"]}, {"$set": {"answers": new_answers}})
    index += 1
    if index % 1000 == 0:
        print(index)

query = {"ban.reason": "ActionFailed"}
all_ban = context_mongo.find(query)
index = 0
for ban in all_ban:
    new_ban = []
    for ban_info in ban["ban"]:
        if ban_info["reason"] == "ActionFailed":
            continue
        new_ban.append(ban_info)
    context_mongo.update_one({"_id": ban["_id"]}, {"$set": {"ban": new_ban}})
    index += 1
    if index % 1000 == 0:
        print(index)
