from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from typing import List, Optional
import os
import random

app = FastAPI()

# CORS settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB Setup
MONGO_URI = os.getenv("MONGO_URI", "your_mongodb_atlas_uri_here")
client = AsyncIOMotorClient(MONGO_URI)
db = client.yt_shorts_db
users_collection = db.users

# Models
class VideoSave(BaseModel):
    user_id: str
    video_id: str
    title: str
    tags: List[str]

YDL_OPTIONS = {
    'format': 'best',
    'quiet': True,
    'no_warnings': True,
    'extract_flat': True, # এটি সার্চ রেজাল্ট দ্রুত করার জন্য খুব জরুরি
}

# --- Helper Function to Search YouTube ---
def youtube_search(query: str, limit: int = 10):
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        # 'ytsearch' ব্যবহার করে সরাসরি ইউটিউবে সার্চ করা হয়
        search_query = f"ytsearch{limit}:{query}"
        results = ydl.extract_info(search_query, download=False)
        
        videos = []
        if 'entries' in results:
            for entry in results['entries']:
                videos.append({
                    "video_id": entry.get('id'),
                    "title": entry.get('title'),
                    "thumbnail": entry.get('thumbnail'),
                    "url": f"https://www.youtube.com/watch?v={entry.get('id')}",
                    "duration": entry.get('duration')
                })
        return videos

# --- API Endpoints ---

# ১. Endless Feed: ইউজারের পছন্দ অনুযায়ী অটো-ফেচ
@app.get("/feed/{user_id}")
async def get_endless_feed(user_id: str):
    try:
        user = await users_collection.find_one({"user_id": user_id})
        
        # যদি ইউজারের কোনো ডাটা না থাকে, তবে ট্রেন্ডিং শর্টস দেখাবে
        if not user or "playlist" not in user or len(user["playlist"]) == 0:
            search_term = "trending shorts 2026" 
        else:
            # ইউজারের প্লেলিস্ট থেকে সবচেয়ে প্রিয় ট্যাগটি নেওয়া
            all_tags = []
            for item in user["playlist"]:
                all_tags.extend(item.get("tags", []))
            
            if all_tags:
                search_term = random.choice(all_tags) + " shorts"
            else:
                search_term = "viral shorts"

        # ইউটিউব থেকে অটোমেটিক ভিডিও ফেচ করা
        videos = youtube_search(search_term, limit=15)
        return {"status": "success", "query_used": search_term, "videos": videos}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ২. Search: লিঙ্ক ছাড়াই কি-ওয়ার্ড দিয়ে সার্চ
@app.get("/search")
async def search_videos(q: str = Query(..., description="Search keyword")):
    try:
        # ইউজার যদি শুধু গান বা টপিকের নাম দেয়, তবে এটি ভিডিও এবং শর্টস উভয়ই খুঁজবে
        results = youtube_search(q, limit=20)
        return {"status": "success", "query": q, "videos": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ৩. Direct Info & Download Link (যখন ইউজার কোনো ভিডিওতে ক্লিক করবে)
@app.get("/info")
async def get_info(url: str):
    try:
        # extract_flat=False করা হয়েছে যাতে আসল ডাউনলোড লিঙ্ক পাওয়া যায়
        with yt_dlp.YoutubeDL({'format': 'best', 'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                "title": info.get('title'),
                "thumbnail": info.get('thumbnail'),
                "download_link": info.get('url'), # Direct MP4/MP3 link
                "tags": info.get('tags', []),
                "video_id": info.get('id'),
            }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ৪. Playlist Tracking (পছন্দ ট্র্যাক করার জন্য)
@app.post("/playlist/add")
async def add_to_playlist(video: VideoSave):
    try:
        await users_collection.update_one(
            {"user_id": video.user_id},
            {"$push": {"playlist": {"video_id": video.video_id, "tags": video.tags, "title": video.title}}},
            upsert=True
        )
        return {"message": "Saved to preferences!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Vercel Handler
def handler(request, context):
    return app(request)
