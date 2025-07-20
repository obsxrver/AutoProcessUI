import os
from pathlib import Path
from typing import List
import instaloader
import cv2


def _login(username: str, password: str | None, remember: bool, session_dir: str = "instagram_sessions"):
    Path(session_dir).mkdir(exist_ok=True)
    session_file = Path(session_dir) / f"{username}.session"
    L = instaloader.Instaloader(download_video_thumbnails=False,
                                download_videos=False,
                                download_comments=False,
                                save_metadata=False,
                                compress_json=False)
    if session_file.exists():
        try:
            L.load_session_from_file(username, str(session_file))
            return L
        except Exception:
            pass
    if password is None:
        raise ValueError("Password required for login")
    L.login(username, password)
    if remember:
        L.save_session_to_file(str(session_file))
    return L


def fetch_profile_images(profile: str, login_user: str, password: str | None = None,
                          remember: bool = False, max_images: int = 20,
                          output_dir: str = "instagram_downloads") -> List[str]:
    L = _login(login_user, password, remember)
    profile_obj = instaloader.Profile.from_username(L.context, profile)
    Path(output_dir).mkdir(exist_ok=True)
    paths: List[str] = []
    count = 0
    for post in profile_obj.get_posts():
        if count >= max_images:
            break
        if post.typename != "GraphImage":
            continue
        fname = Path(output_dir) / f"{post.date_utc.strftime('%Y%m%d_%H%M%S')}_{post.mediaid}.jpg"
        if L.download_pic(str(fname), post.url, post.date_utc):
            paths.append(str(fname))
            count += 1
    return paths


def filter_single_human_images(image_paths: List[str]) -> List[str]:
    keep: List[str] = []
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    for p in image_paths:
        try:
            img = cv2.imread(p)
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
            if len(faces) == 1:
                keep.append(p)
        except Exception:
            continue
    return keep
