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

class VideoSave(BaseModel):
    user_id: str
    video_id: str
    title: str
    tags: List[str]

# Optimized YDL Options for speed and more data
YDL_OPTIONS = {
    'format': 'best',
    'quiet': True,
    'no_warnings': True,
    'extract_flat': True, 
}

# --- Helper Function for Large Scale Search ---
def youtube_search_large(query: str, page: int = 1, limit_per_page: int = 30):
    # ইউটিউবে যত বেশি রেজাল্ট চাই, তত বেশি লিমিট দিতে হয়
    # পেজ ১ এর জন্য ০-৩০, পেজ ২ এর জন্য ৩১-৬০ ইত্যাদি
    total_needed = page * limit_per_page
    
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        search_query = f"ytsearch{total_needed}:{query}"
        results = ydl.extract_info(search_query, download=False)
        
        videos = []
        if 'entries' in results:
            # শুধুমাত্র বর্তমান পেজের ভিডিওগুলো স্লাইস করে নেওয়া
            start_index = (page - 1) * limit_per_page
            end_index = page * limit_per_page
            page_entries = results['entries'][start_index:end_index]
            
            for entry in page_entries:
                videos.append({
                    "video_id": entry.get('id'),
                    "title": entry.get('title'),
                    "thumbnail": entry.get('thumbnail'), # If null, app should use default
                    "url": f"https://www.youtube.com/watch?v={entry.get('id')}",
                    "duration": float(entry.get('duration', 0))
                })
        return videos

# --- API Endpoints ---

# ১. Search: আনলিমিটেড ফিলিংয়ের জন্য পেজিনেশন যুক্ত
@app.get("/search")
async def search_videos(
    q: str = Query(..., description="Search keyword"), 
    page: int = Query(1, description="Page number for endless scroll")
):
    try:
        results = youtube_search_large(q, page=page)
        
        # আপনার দেওয়া স্যাম্পল JSON ফরম্যাটে রেসপন্স
        return {
            "status": "success", 
            "query": q, 
            "page": page,
            "videos": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ২. Endless Feed: ইউজারের পছন্দের উপর ভিত্তি করে অটো-ফেচ
@app.get("/feed/{user_id}")
async def get_endless_feed(user_id: str, page: int = 1):
    try:
        user = await users_collection.find_one({"user_id": user_id})
        
        if not user or "playlist" not in user or len(user["playlist"]) == 0:
            search_term = "trending shorts 2026" 
        else:
            all_tags = []
            for item in user["playlist"]:
                all_tags.extend(item.get("tags", []))
            search_term = random.choice(all_tags) + " shorts" if all_tags else "viral shorts"

        videos = youtube_search_large(search_term, page=page)
        
        return {
            "status": "success", 
            "query": search_term, 
            "page": page,
            "videos": videos
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ৩. Direct Info & Download Link
@app.get("/info")
async def get_info(url: str):
    try:
        with yt_dlp.YoutubeDL({'format': 'best', 'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                "title": info.get('title'),
                "thumbnail": info.get('thumbnail'),
                "download_link": info.get('url'),
                "tags": info.get('tags', []),
                "video_id": info.get('id'),
            }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ৪. Playlist Tracking
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

def handler(request, context):
    return app(request)
