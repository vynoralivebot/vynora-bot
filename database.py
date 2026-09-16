import os
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://...") 

try:
    client = MongoClient(MONGO_URI)
    # Ping the database to verify connection on startup
    client.admin.command('ping')
    print("✅ Successfully connected to MongoDB!")
except Exception as e:
    print(f"❌ MongoDB Connection Error: {e}")

db = client["vynora_live_db"]

# Collections
users_col = db["users"]
hosts_col = db["hosts"]
bookings_col = db["bookings"]
recharges_col = db["recharges"]
withdrawals_col = db["withdrawals"]
chats_col = db["chats"]
