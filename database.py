import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
client = AsyncIOMotorClient(MONGO_URI)
db = client.telegram_host_platform

users_collection = db.users
hosts_collection = db.hosts
bookings_collection = db.bookings
transactions_collection = db.transactions
