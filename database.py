import os
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://...") # Apni MongoDB URI yahan ya Render Env me dalein
client = MongoClient(MONGO_URI)
db = client["vynora_live_db"]

# Collections
users_col = db["users"]
hosts_col = db["hosts"]
bookings_col = db["bookings"]
recharges_col = db["recharges"]
withdrawals_col = db["withdrawals"]
chats_col = db["chats"]
